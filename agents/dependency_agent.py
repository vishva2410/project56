# agents/dependency_agent.py
"""
Dependency Agent — parses import statements from Python files, builds
a dependency graph, and answers "what depends on X?" queries.

Supports two backends:
  • Neo4j  — if NEO4J_URI is set in .env
  • In-memory networkx graph — zero-setup fallback
"""

import ast
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

from agents.base import get_llm, get_parser
from rag.code_parser import SKIP_DIRS

load_dotenv()

# ---------------------------------------------------------------------------
# Try to import neo4j; fall back to networkx if unavailable / not configured
# ---------------------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

_neo4j_available = False
try:
    import neo4j as _neo4j_mod
    if NEO4J_URI:
        _neo4j_available = True
except ImportError:
    pass

import networkx as nx


# ============================================================================
# Graph backend abstraction
# ============================================================================
class _NetworkXBackend:
    """In-memory graph using networkx (zero-setup fallback)."""

    def __init__(self):
        self.G = nx.DiGraph()

    def add_file_node(self, filepath: str, module: str):
        self.G.add_node(filepath, kind="file", module=module)

    def add_definition(self, filepath: str, name: str, kind: str):
        node_id = f"{filepath}::{name}"
        self.G.add_node(node_id, kind=kind, defined_in=filepath)
        self.G.add_edge(filepath, node_id, rel="DEFINES")

    def add_import(self, source_file: str, target_module: str):
        self.G.add_edge(source_file, target_module, rel="IMPORTS")

    def get_dependents(self, target: str) -> List[str]:
        """Files/modules that import *target*."""
        results = set()
        for u, v, data in self.G.edges(data=True):
            if data.get("rel") == "IMPORTS" and (v == target or target in v):
                results.add(u)
        return sorted(results)

    def get_dependencies(self, source: str) -> List[str]:
        """Modules that *source* imports."""
        results = set()
        for u, v, data in self.G.edges(data=True):
            if data.get("rel") == "IMPORTS" and (u == source or source in u):
                results.add(v)
        return sorted(results)

    def get_definitions(self, filepath: str) -> List[Dict]:
        """Functions / classes defined in a file."""
        defs = []
        for u, v, data in self.G.edges(data=True):
            if data.get("rel") == "DEFINES" and u == filepath:
                node = self.G.nodes[v]
                defs.append({"name": v.split("::")[-1], "kind": node.get("kind", "unknown")})
        return defs

    def all_files(self) -> List[str]:
        return [n for n, d in self.G.nodes(data=True) if d.get("kind") == "file"]

    def export_graph(self) -> Dict:
        nodes = [{"id": n, **d} for n, d in self.G.nodes(data=True)]
        edges = [{"source": u, "target": v, **d} for u, v, d in self.G.edges(data=True)]
        return {"nodes": nodes, "edges": edges}

    def clear(self):
        self.G.clear()


class _Neo4jBackend:
    """Neo4j graph database backend."""

    def __init__(self):
        self.driver = _neo4j_mod.GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
        )

    def _run(self, query: str, **params):
        with self.driver.session() as session:
            return list(session.run(query, **params))

    def add_file_node(self, filepath: str, module: str):
        self._run(
            "MERGE (f:File {path: $path}) SET f.module = $module",
            path=filepath, module=module,
        )

    def add_definition(self, filepath: str, name: str, kind: str):
        self._run(
            f"MERGE (d:{kind.capitalize()} {{name: $name, defined_in: $fp}}) "
            f"WITH d "
            f"MATCH (f:File {{path: $fp}}) "
            f"MERGE (f)-[:DEFINES]->(d)",
            name=name, fp=filepath,
        )

    def add_import(self, source_file: str, target_module: str):
        self._run(
            "MERGE (s:File {path: $src}) "
            "MERGE (t:Module {name: $tgt}) "
            "MERGE (s)-[:IMPORTS]->(t)",
            src=source_file, tgt=target_module,
        )

    def get_dependents(self, target: str) -> List[str]:
        records = self._run(
            "MATCH (f:File)-[:IMPORTS]->(m) "
            "WHERE m.name CONTAINS $target OR f.path CONTAINS $target "
            "RETURN DISTINCT f.path AS path",
            target=target,
        )
        return sorted(r["path"] for r in records)

    def get_dependencies(self, source: str) -> List[str]:
        records = self._run(
            "MATCH (f:File)-[:IMPORTS]->(m) "
            "WHERE f.path CONTAINS $source "
            "RETURN DISTINCT m.name AS name",
            source=source,
        )
        return sorted(r["name"] for r in records)

    def get_definitions(self, filepath: str) -> List[Dict]:
        records = self._run(
            "MATCH (f:File {path: $fp})-[:DEFINES]->(d) "
            "RETURN d.name AS name, labels(d) AS labels",
            fp=filepath,
        )
        return [{"name": r["name"], "kind": r["labels"][0].lower()} for r in records]

    def all_files(self) -> List[str]:
        records = self._run("MATCH (f:File) RETURN f.path AS path")
        return sorted(r["path"] for r in records)

    def export_graph(self) -> Dict:
        nodes_raw = self._run("MATCH (n) RETURN id(n) AS id, labels(n) AS labels, properties(n) AS props")
        edges_raw = self._run("MATCH (a)-[r]->(b) RETURN id(a) AS src, id(b) AS tgt, type(r) AS rel")
        nodes = [{"id": r["id"], "labels": r["labels"], **r["props"]} for r in nodes_raw]
        edges = [{"source": r["src"], "target": r["tgt"], "rel": r["rel"]} for r in edges_raw]
        return {"nodes": nodes, "edges": edges}

    def clear(self):
        self._run("MATCH (n) DETACH DELETE n")


# ============================================================================
# Dependency Agent
# ============================================================================
class DependencyAgent:
    """Parse imports, build a dependency graph, answer dependency questions."""

    def __init__(self, use_neo4j: Optional[bool] = None):
        if use_neo4j is None:
            use_neo4j = _neo4j_available

        if use_neo4j and _neo4j_available:
            print("[DependencyAgent] Using Neo4j backend")
            self.backend = _Neo4jBackend()
        else:
            print("[DependencyAgent] Using in-memory networkx backend")
            self.backend = _NetworkXBackend()

        self.llm = get_llm()
        self.parser = get_parser()

    # ------------------------------------------------------------------
    # Graph building
    # ------------------------------------------------------------------
    def build_graph(self, repo_path: str):
        """Parse every .py file's imports and build the dependency graph."""
        repo_path = os.path.abspath(repo_path)
        self.backend.clear()

        file_count = 0
        import_count = 0
        def_count = 0

        for dirpath, dirnames, filenames in os.walk(repo_path):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue

                fpath = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(fpath, repo_path)
                module_name = rel_path.replace(os.sep, ".").removesuffix(".py")

                self.backend.add_file_node(rel_path, module_name)
                file_count += 1

                try:
                    source = Path(fpath).read_text(errors="replace")
                    tree = ast.parse(source)
                except (SyntaxError, Exception):
                    continue

                # Extract imports
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self.backend.add_import(rel_path, alias.name)
                            import_count += 1
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            self.backend.add_import(rel_path, node.module)
                            import_count += 1

                # Extract top-level definitions
                for node in ast.iter_child_nodes(tree):
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                        self.backend.add_definition(rel_path, node.name, "function")
                        def_count += 1
                    elif isinstance(node, ast.ClassDef):
                        self.backend.add_definition(rel_path, node.name, "class")
                        def_count += 1

        print(
            f"[DependencyAgent] Graph built — "
            f"{file_count} files, {import_count} imports, {def_count} definitions"
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def query_dependents(self, target: str) -> List[str]:
        """What depends on *target*? (files that import it)."""
        return self.backend.get_dependents(target)

    def query_dependencies(self, target: str) -> List[str]:
        """What does *target* depend on? (modules it imports)."""
        return self.backend.get_dependencies(target)

    def get_definitions(self, filepath: str) -> List[Dict]:
        """Functions and classes defined in a file."""
        return self.backend.get_definitions(filepath)

    def get_import_graph(self) -> Dict:
        """Export the full graph for visualization."""
        return self.backend.export_graph()

    def answer_question(self, question: str) -> Dict:
        """Use LLM to interpret a dependency question and answer it."""
        # Gather graph summary as context
        all_files = self.backend.all_files()
        graph_data = self.backend.export_graph()

        # Build a concise textual summary of the graph
        summary_lines = [f"Files in graph: {len(all_files)}"]
        edges_by_type: Dict[str, int] = {}
        for edge in graph_data.get("edges", []):
            rel = edge.get("rel", "UNKNOWN")
            edges_by_type[rel] = edges_by_type.get(rel, 0) + 1
        for rel, count in edges_by_type.items():
            summary_lines.append(f"  {rel}: {count} relationships")

        # Show a sample of import edges for context
        import_edges = [e for e in graph_data.get("edges", []) if e.get("rel") == "IMPORTS"][:20]
        for e in import_edges:
            summary_lines.append(f"  {e['source']} --IMPORTS--> {e['target']}")

        context = "\n".join(summary_lines)

        from langchain_core.prompts import ChatPromptTemplate
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a dependency analysis expert. Answer questions about code "
             "dependencies using the provided graph data. Be specific about which "
             "files import what.\n\nDependency graph:\n{context}"),
            ("human", "{question}"),
        ])

        chain = prompt | self.llm | self.parser
        answer = chain.invoke({"context": context, "question": question})

        return {
            "answer": answer,
            "files_in_graph": len(all_files),
        }


# ------------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------------
if __name__ == "__main__":
    agent = DependencyAgent()
    agent.build_graph(".")

    print("\n=== Dependents of 'agents.base' ===")
    print(agent.query_dependents("agents.base"))

    print("\n=== Dependencies of 'main.py' ===")
    print(agent.query_dependencies("main.py"))

    print("\n=== Full graph export ===")
    import json
    graph = agent.get_import_graph()
    print(f"Nodes: {len(graph['nodes'])}, Edges: {len(graph['edges'])}")
