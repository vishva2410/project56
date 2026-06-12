# rag/code_parser.py
"""
Git repo cloning and Python AST-based code parsing.
Extracts functions, classes, and module-level code from .py files.
For non-Python files, returns the raw content with basic metadata.
"""

import ast
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import git


# ---------------------------------------------------------------------------
# File-extension allow-list (expand as needed)
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".go", ".rs", ".rb", ".php",
    ".c", ".cpp", ".h", ".hpp", ".cs",
    ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml",
    ".md", ".txt", ".rst",
    ".sql", ".sh", ".bash",
}

# Directories to always skip
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".env", ".tox", ".mypy_cache", ".pytest_cache",
    "dist", "build", "egg-info", ".eggs", ".idea", ".vscode",
}


class CodeParser:
    """Clone a Git repo and extract structured code chunks."""

    def __init__(self, clone_dir: Optional[str] = None):
        """
        Args:
            clone_dir: Directory to clone repos into.
                       If None, a temp directory is created.
        """
        self.clone_dir = clone_dir or os.path.join(
            tempfile.gettempdir(), "codebase_ai_repos"
        )
        os.makedirs(self.clone_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def clone_repo(self, github_url: str, repo_name: Optional[str] = None) -> str:
        """Clone a GitHub repo and return the local path.

        If the repo already exists locally it is removed and re-cloned
        to guarantee a fresh copy.
        """
        if repo_name is None:
            repo_name = github_url.rstrip("/").split("/")[-1].replace(".git", "")

        dest = os.path.join(self.clone_dir, repo_name)

        if os.path.exists(dest):
            shutil.rmtree(dest)

        print(f"[CodeParser] Cloning {github_url} → {dest}")
        git.Repo.clone_from(github_url, dest, depth=1)  # shallow clone
        print(f"[CodeParser] Clone complete — {dest}")
        return dest

    def parse_repo(self, repo_path: str) -> List[Dict]:
        """Walk *repo_path* and return structured code chunks.

        Each chunk is a dict with keys:
            content, source, module, language, chunk_type,
            name, start_line, end_line, docstring
        """
        repo_path = os.path.abspath(repo_path)
        chunks: List[Dict] = []

        for dirpath, dirnames, filenames in os.walk(repo_path):
            # Prune skippable dirs in-place so os.walk doesn't descend
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                ext = Path(fname).suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                rel_path = os.path.relpath(fpath, repo_path)
                try:
                    source_code = Path(fpath).read_text(errors="replace")
                except Exception:
                    continue

                if ext == ".py":
                    chunks.extend(self._parse_python(source_code, rel_path))
                else:
                    # Non-Python: store the whole file as a single chunk
                    lang = self._ext_to_language(ext)
                    chunks.append({
                        "content": source_code,
                        "source": rel_path,
                        "module": self._path_to_module(rel_path),
                        "language": lang,
                        "chunk_type": "file",
                        "name": fname,
                        "start_line": 1,
                        "end_line": source_code.count("\n") + 1,
                        "docstring": "",
                    })

        print(f"[CodeParser] Parsed {len(chunks)} chunks from {repo_path}")
        return chunks

    def get_file_tree(self, repo_path: str) -> Dict:
        """Return a nested dict representing the repo's file tree."""
        repo_path = os.path.abspath(repo_path)
        tree: Dict = {"name": os.path.basename(repo_path), "type": "directory", "children": []}

        for dirpath, dirnames, filenames in os.walk(repo_path):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            rel = os.path.relpath(dirpath, repo_path)

            # Navigate to the right sub-dict
            node = tree
            if rel != ".":
                for part in rel.split(os.sep):
                    for child in node["children"]:
                        if child["name"] == part and child["type"] == "directory":
                            node = child
                            break

            # Add sub-directories
            for d in sorted(dirnames):
                node["children"].append({"name": d, "type": "directory", "children": []})

            # Add files
            for f in sorted(filenames):
                ext = Path(f).suffix.lower()
                if ext in SUPPORTED_EXTENSIONS:
                    node["children"].append({"name": f, "type": "file"})

        return tree

    # ------------------------------------------------------------------
    # Python-specific AST parsing
    # ------------------------------------------------------------------
    def _parse_python(self, source: str, rel_path: str) -> List[Dict]:
        """Use the ast module to extract functions and classes."""
        chunks: List[Dict] = []
        module_name = self._path_to_module(rel_path)
        lines = source.splitlines(keepends=True)

        try:
            tree = ast.parse(source)
        except SyntaxError:
            # If we can't parse it, store as a raw file chunk
            chunks.append({
                "content": source,
                "source": rel_path,
                "module": module_name,
                "language": "python",
                "chunk_type": "file",
                "name": Path(rel_path).name,
                "start_line": 1,
                "end_line": len(lines),
                "docstring": "",
            })
            return chunks

        # Extract top-level functions and classes
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                chunks.append(self._node_to_chunk(node, lines, rel_path, module_name, "function"))
            elif isinstance(node, ast.ClassDef):
                chunks.append(self._node_to_chunk(node, lines, rel_path, module_name, "class"))
                # Also extract methods within the class
                for item in ast.iter_child_nodes(node):
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        chunks.append(
                            self._node_to_chunk(
                                item, lines, rel_path, module_name,
                                "method", parent_class=node.name,
                            )
                        )

        # Module-level code (imports, constants, etc.) — everything NOT
        # inside a function/class
        module_level_lines = self._extract_module_level(tree, lines)
        if module_level_lines.strip():
            chunks.append({
                "content": module_level_lines,
                "source": rel_path,
                "module": module_name,
                "language": "python",
                "chunk_type": "module_level",
                "name": Path(rel_path).stem,
                "start_line": 1,
                "end_line": len(lines),
                "docstring": ast.get_docstring(tree) or "",
            })

        return chunks

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _node_to_chunk(
        node: ast.AST,
        lines: List[str],
        rel_path: str,
        module_name: str,
        chunk_type: str,
        parent_class: Optional[str] = None,
    ) -> Dict:
        start = node.lineno - 1  # 0-indexed
        end = node.end_lineno     # exclusive upper bound
        content = "".join(lines[start:end])
        name = node.name
        if parent_class:
            name = f"{parent_class}.{name}"
        return {
            "content": content,
            "source": rel_path,
            "module": module_name,
            "language": "python",
            "chunk_type": chunk_type,
            "name": name,
            "start_line": node.lineno,
            "end_line": node.end_lineno,
            "docstring": ast.get_docstring(node) or "",
        }

    @staticmethod
    def _extract_module_level(tree: ast.Module, lines: List[str]) -> str:
        """Return source lines that are NOT inside a function or class."""
        covered: set[int] = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                    covered.add(ln)

        module_lines = []
        for i, line in enumerate(lines, start=1):
            if i not in covered:
                module_lines.append(line)
        return "".join(module_lines)

    @staticmethod
    def _path_to_module(rel_path: str) -> str:
        """Convert 'agents/base.py' → 'agents.base'."""
        p = rel_path.replace(os.sep, ".")
        if p.endswith(".py"):
            p = p[:-3]
        return p

    @staticmethod
    def _ext_to_language(ext: str) -> str:
        mapping = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".jsx": "javascript", ".tsx": "typescript",
            ".java": "java", ".go": "go", ".rs": "rust",
            ".rb": "ruby", ".php": "php",
            ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
            ".cs": "csharp",
            ".html": "html", ".css": "css", ".scss": "scss",
            ".json": "json", ".yaml": "yaml", ".yml": "yaml",
            ".toml": "toml", ".md": "markdown", ".txt": "text",
            ".rst": "rst", ".sql": "sql",
            ".sh": "bash", ".bash": "bash",
        }
        return mapping.get(ext, "text")
