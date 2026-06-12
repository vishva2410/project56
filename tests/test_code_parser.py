# tests/test_code_parser.py
"""Tests for rag/code_parser.py — AST parsing and file tree."""

import os
import tempfile
from pathlib import Path

from rag.code_parser import CodeParser


def _make_sample_repo(tmp: str):
    """Create a tiny fake repo for testing."""
    os.makedirs(os.path.join(tmp, "services"), exist_ok=True)

    Path(os.path.join(tmp, "main.py")).write_text(
        'from services.auth import login\n\ndef main():\n    login("admin")\n\nif __name__ == "__main__":\n    main()\n'
    )
    Path(os.path.join(tmp, "services", "__init__.py")).write_text("")
    Path(os.path.join(tmp, "services", "auth.py")).write_text(
        'import hashlib\n\ndef login(user: str):\n    """Authenticate a user."""\n    return True\n\n\nclass AuthManager:\n    def __init__(self):\n        self.users = {}\n\n    def register(self, user):\n        self.users[user] = True\n'
    )
    Path(os.path.join(tmp, "README.md")).write_text("# Test Project\nA test.\n")


def test_parse_repo_returns_chunks():
    with tempfile.TemporaryDirectory() as tmp:
        _make_sample_repo(tmp)
        parser = CodeParser()
        chunks = parser.parse_repo(tmp)

        assert len(chunks) > 0
        # Should have at least: main.py's main(), auth.py's login(), AuthManager, module-level code, README
        names = [c["name"] for c in chunks]
        assert any("main" in n for n in names)
        assert any("login" in n for n in names)
        assert any("AuthManager" in n for n in names)


def test_chunks_have_required_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        _make_sample_repo(tmp)
        parser = CodeParser()
        chunks = parser.parse_repo(tmp)

        required_keys = {"content", "source", "module", "language", "chunk_type", "name"}
        for chunk in chunks:
            assert required_keys.issubset(chunk.keys()), f"Missing keys in {chunk.get('name')}"


def test_file_tree_structure():
    with tempfile.TemporaryDirectory() as tmp:
        _make_sample_repo(tmp)
        parser = CodeParser()
        tree = parser.get_file_tree(tmp)

        assert tree["type"] == "directory"
        child_names = [c["name"] for c in tree["children"]]
        assert "main.py" in child_names
        assert "services" in child_names
        assert "README.md" in child_names


def test_python_ast_extracts_docstrings():
    with tempfile.TemporaryDirectory() as tmp:
        _make_sample_repo(tmp)
        parser = CodeParser()
        chunks = parser.parse_repo(tmp)

        login_chunk = next((c for c in chunks if c["name"] == "login"), None)
        assert login_chunk is not None
        assert login_chunk["docstring"] == "Authenticate a user."


def test_non_python_files_are_single_chunk():
    with tempfile.TemporaryDirectory() as tmp:
        _make_sample_repo(tmp)
        parser = CodeParser()
        chunks = parser.parse_repo(tmp)

        md_chunks = [c for c in chunks if c["source"] == "README.md"]
        assert len(md_chunks) == 1
        assert md_chunks[0]["chunk_type"] == "file"
        assert md_chunks[0]["language"] == "markdown"
