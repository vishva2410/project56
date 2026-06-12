# agents/architecture_agent.py
"""
Architecture Agent — analyzes repo structure to detect architectural
patterns, frameworks, and generate human-readable architecture summaries.
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict

from agents.base import get_llm, get_parser
from rag.code_parser import CodeParser, SKIP_DIRS, SUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------
FRAMEWORK_MARKERS = {
    # Python
    "fastapi": {"files": ["main.py"], "imports": ["fastapi"], "deps": ["fastapi"]},
    "flask": {"files": ["app.py", "wsgi.py"], "imports": ["flask"], "deps": ["flask"]},
    "django": {"files": ["manage.py", "settings.py"], "imports": ["django"], "deps": ["django"]},
    # JavaScript / TypeScript
    "react": {"files": ["App.jsx", "App.tsx"], "imports": ["react"], "deps": ["react"]},
    "nextjs": {"files": ["next.config.js", "next.config.mjs"], "imports": ["next"], "deps": ["next"]},
    "express": {"files": [], "imports": ["express"], "deps": ["express"]},
    "vue": {"files": ["App.vue"], "imports": ["vue"], "deps": ["vue"]},
    # Other
    "spring": {"files": [], "imports": ["springframework"], "deps": ["spring-boot"]},
}

ARCHITECTURE_PATTERNS = {
    "mvc": {
        "indicator_dirs": {"models", "views", "controllers"},
        "description": "Model-View-Controller",
    },
    "service_layer": {
        "indicator_dirs": {"services", "routes", "api", "handlers"},
        "description": "Service / Route layer architecture",
    },
    "clean_architecture": {
        "indicator_dirs": {"domain", "usecases", "infrastructure", "interfaces"},
        "description": "Clean Architecture (Onion / Hexagonal)",
    },
    "monorepo": {
        "indicator_dirs": {"packages", "apps", "libs"},
        "description": "Monorepo (multi-package)",
    },
    "microservices": {
        "indicator_dirs": {"gateway", "auth-service", "user-service"},
        "description": "Microservices",
    },
}


@dataclass
class ArchitectureReport:
    """Structured result from architecture analysis."""
    frameworks: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    languages: Dict[str, int] = field(default_factory=dict)       # lang -> file count
    top_level_dirs: List[str] = field(default_factory=list)
    total_files: int = 0
    total_lines: int = 0
    entry_points: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


class ArchitectureAgent:
    """Analyze repository structure and detect patterns."""

    def __init__(self):
        self.llm = get_llm(temperature=0.1)
        self.parser = get_parser()
        self._code_parser = CodeParser()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def analyze(self, repo_path: str) -> ArchitectureReport:
        """Run full architecture analysis on a local repo."""
        repo_path = os.path.abspath(repo_path)
        report = ArchitectureReport()

        # 1. Gather structural info
        report.top_level_dirs = self._top_level_dirs(repo_path)
        lang_counts, total_files, total_lines = self._count_languages(repo_path)
        report.languages = dict(sorted(lang_counts.items(), key=lambda x: -x[1]))
        report.total_files = total_files
        report.total_lines = total_lines

        # 2. Detect frameworks
        report.frameworks = self._detect_frameworks(repo_path)

        # 3. Detect architecture patterns
        dir_set = set(report.top_level_dirs)
        for pattern_name, info in ARCHITECTURE_PATTERNS.items():
            if info["indicator_dirs"] & dir_set:
                report.patterns.append(f"{pattern_name} ({info['description']})")

        # 4. Find entry points
        report.entry_points = self._find_entry_points(repo_path)

        # 5. Generate LLM summary
        report.summary = self._generate_summary(report, repo_path)

        return report

    def get_file_tree(self, repo_path: str) -> Dict:
        """Return structured file tree (delegates to CodeParser)."""
        return self._code_parser.get_file_tree(repo_path)

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------
    def _top_level_dirs(self, repo_path: str) -> List[str]:
        """List top-level directories (excluding noise)."""
        return sorted(
            d for d in os.listdir(repo_path)
            if os.path.isdir(os.path.join(repo_path, d)) and d not in SKIP_DIRS and not d.startswith(".")
        )

    def _count_languages(self, repo_path: str):
        """Count files and lines per language."""
        lang_counts: Dict[str, int] = {}
        total_files = 0
        total_lines = 0

        for dirpath, dirnames, filenames in os.walk(repo_path):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                lang = CodeParser._ext_to_language(ext)
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
                total_files += 1
                try:
                    lines = Path(os.path.join(dirpath, fname)).read_text(errors="replace").count("\n")
                    total_lines += lines
                except Exception:
                    pass

        return lang_counts, total_files, total_lines

    def _detect_frameworks(self, repo_path: str) -> List[str]:
        """Detect frameworks by checking files, dependency manifests, and imports."""
        detected: List[str] = []
        all_files: Set[str] = set()

        for dirpath, dirnames, filenames in os.walk(repo_path):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                all_files.add(f)

        # Check dependency manifests
        dep_text = ""
        for manifest in ("requirements.txt", "Pipfile", "pyproject.toml", "package.json", "pom.xml", "build.gradle"):
            mpath = os.path.join(repo_path, manifest)
            if os.path.isfile(mpath):
                try:
                    dep_text += Path(mpath).read_text(errors="replace").lower()
                except Exception:
                    pass

        for framework, markers in FRAMEWORK_MARKERS.items():
            # Check marker files
            if any(f in all_files for f in markers["files"]):
                detected.append(framework)
                continue
            # Check deps
            if any(d in dep_text for d in markers["deps"]):
                detected.append(framework)
                continue

        return detected

    def _find_entry_points(self, repo_path: str) -> List[str]:
        """Find likely entry point files."""
        candidates = [
            "main.py", "app.py", "server.py", "wsgi.py", "manage.py",
            "index.js", "index.ts", "server.js", "server.ts",
            "App.jsx", "App.tsx",
        ]
        found = []
        for c in candidates:
            if os.path.isfile(os.path.join(repo_path, c)):
                found.append(c)

        # Also check for __main__.py anywhere
        for dirpath, _, filenames in os.walk(repo_path):
            if "__main__.py" in filenames:
                found.append(os.path.relpath(os.path.join(dirpath, "__main__.py"), repo_path))

        return found

    def _generate_summary(self, report: ArchitectureReport, repo_path: str) -> str:
        """Use Gemini to produce a plain-text architecture summary."""
        facts = (
            f"Repository: {os.path.basename(repo_path)}\n"
            f"Total files: {report.total_files}\n"
            f"Total lines: {report.total_lines}\n"
            f"Languages: {json.dumps(report.languages)}\n"
            f"Top-level directories: {report.top_level_dirs}\n"
            f"Detected frameworks: {report.frameworks}\n"
            f"Detected patterns: {report.patterns}\n"
            f"Entry points: {report.entry_points}\n"
        )

        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a senior software architect. Given the structural facts about "
             "a code repository, produce a clear 4-6 sentence architecture summary. "
             "Mention the tech stack, the architectural style, key directories, "
             "and how the codebase is organized. Be concise."),
            ("human", "{facts}"),
        ])

        chain = prompt | self.llm | self.parser
        return chain.invoke({"facts": facts})


# ------------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------------
if __name__ == "__main__":
    agent = ArchitectureAgent()
    report = agent.analyze(".")
    print(json.dumps(report.to_dict(), indent=2))
