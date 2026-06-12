# tests/test_agents.py
"""Tests for the core agents — mostly structural / smoke tests
that don't require a Gemini API key."""

import os
import tempfile
from pathlib import Path

from rag.code_parser import CodeParser
from rag.chunking import CodeChunker
from agents.dependency_agent import DependencyAgent


def _make_sample_repo(tmp: str):
    """Create a tiny fake repo."""
    os.makedirs(os.path.join(tmp, "models"), exist_ok=True)
    Path(os.path.join(tmp, "main.py")).write_text(
        "from models.user import User\nimport os\n\ndef main():\n    pass\n"
    )
    Path(os.path.join(tmp, "models", "__init__.py")).write_text("")
    Path(os.path.join(tmp, "models", "user.py")).write_text(
        "import hashlib\n\nclass User:\n    def __init__(self, name):\n        self.name = name\n"
    )


def test_code_chunker_produces_documents():
    with tempfile.TemporaryDirectory() as tmp:
        _make_sample_repo(tmp)
        parser = CodeParser()
        raw = parser.parse_repo(tmp)
        chunker = CodeChunker()
        docs = chunker.chunks_to_documents(raw)

        assert len(docs) > 0
        for doc in docs:
            assert doc.page_content
            assert "source" in doc.metadata


def test_dependency_agent_networkx_backend():
    with tempfile.TemporaryDirectory() as tmp:
        _make_sample_repo(tmp)
        agent = DependencyAgent(use_neo4j=False)
        agent.build_graph(tmp)

        # main.py should import models.user
        deps = agent.query_dependencies("main.py")
        assert any("models.user" in d for d in deps)

        # models/user.py should import hashlib
        deps2 = agent.query_dependencies("models/user.py")
        assert "hashlib" in deps2

        # Graph export should have nodes and edges
        graph = agent.get_import_graph()
        assert len(graph["nodes"]) > 0
        assert len(graph["edges"]) > 0


def test_dependency_agent_definitions():
    with tempfile.TemporaryDirectory() as tmp:
        _make_sample_repo(tmp)
        agent = DependencyAgent(use_neo4j=False)
        agent.build_graph(tmp)

        defs = agent.get_definitions("models/user.py")
        names = [d["name"] for d in defs]
        assert "User" in names
