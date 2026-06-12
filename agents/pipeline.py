# agents/pipeline.py
"""
LangGraph pipeline — wires all four agents (Retrieval, Architecture,
Dependency, Documentation) into a single stateful graph.

Two main flows:
  1. Ingest:  clone repo → parse → index → analyze → build deps → summarize
  2. Query:   accept question → route → retrieve → answer
"""

import os
import shutil
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

from agents.retrieval_agent import RetrievalAgent
from agents.architecture_agent import ArchitectureAgent
from agents.dependency_agent import DependencyAgent
from agents.documentation_agent import DocumentationAgent
from agents.router import QuestionRouter
from rag.code_parser import CodeParser
from rag.chunking import CodeChunker


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------
class PipelineState(TypedDict, total=False):
    # Ingest inputs
    repo_url: str
    repo_path: str
    repo_id: str

    # Ingest outputs
    file_count: int
    chunk_count: int
    architecture_report: Dict
    dependency_graph: Dict
    documentation_summaries: Dict
    file_tree: Dict

    # Query inputs
    question: str

    # Query outputs
    route: str
    answer: str
    sources: List[str]
    agent_used: str

    # Control
    error: str
    status: str


# ---------------------------------------------------------------------------
# Pipeline builder
# ---------------------------------------------------------------------------
class CodebasePipeline:
    """Orchestrates the full ingest + query flow."""

    def __init__(
        self,
        chroma_dir: str = "./chroma_db",
        doc_cache: str = "./doc_cache.json",
        clone_dir: Optional[str] = None,
    ):
        self.chroma_dir = chroma_dir
        self.doc_cache = doc_cache

        # Agents
        self.code_parser = CodeParser(clone_dir=clone_dir)
        self.chunker = CodeChunker()
        self.retrieval = RetrievalAgent(persist_dir=chroma_dir)
        self.architecture = ArchitectureAgent()
        self.dependency = DependencyAgent()
        self.documentation = DocumentationAgent(cache_path=doc_cache)
        self.router = QuestionRouter()

        # Build LangGraph
        self._ingest_graph = self._build_ingest_graph()
        self._query_graph = self._build_query_graph()

    # ==================================================================
    # INGEST GRAPH
    # ==================================================================
    def _build_ingest_graph(self) -> StateGraph:
        g = StateGraph(PipelineState)

        g.add_node("clone", self._node_clone)
        g.add_node("parse_and_index", self._node_parse_and_index)
        g.add_node("analyze_architecture", self._node_architecture)
        g.add_node("build_dependencies", self._node_dependencies)
        g.add_node("generate_docs", self._node_documentation)

        g.set_entry_point("clone")
        g.add_edge("clone", "parse_and_index")
        g.add_edge("parse_and_index", "analyze_architecture")
        g.add_edge("analyze_architecture", "build_dependencies")
        g.add_edge("build_dependencies", "generate_docs")
        g.add_edge("generate_docs", END)

        return g.compile()

    def _node_clone(self, state: PipelineState) -> Dict:
        """Clone the repo (or use an existing local path)."""
        repo_url = state.get("repo_url", "")
        repo_path = state.get("repo_path", "")

        if repo_path and os.path.isdir(repo_path):
            repo_id = os.path.basename(os.path.abspath(repo_path))
            print(f"[Pipeline] Using existing repo at {repo_path}")
            return {"repo_path": repo_path, "repo_id": repo_id, "status": "cloned"}

        if repo_url:
            repo_path = self.code_parser.clone_repo(repo_url)
            repo_id = os.path.basename(repo_path)
            return {"repo_path": repo_path, "repo_id": repo_id, "status": "cloned"}

        return {"error": "No repo_url or repo_path provided", "status": "error"}

    def _node_parse_and_index(self, state: PipelineState) -> Dict:
        """Parse the repo and index into ChromaDB."""
        repo_path = state["repo_path"]

        # Clear old index
        if os.path.isdir(self.chroma_dir):
            shutil.rmtree(self.chroma_dir)

        raw_chunks = self.code_parser.parse_repo(repo_path)
        documents = self.chunker.chunks_to_documents(raw_chunks)
        self.retrieval.index_documents(documents)

        return {
            "file_count": len(set(c["source"] for c in raw_chunks)),
            "chunk_count": len(documents),
            "status": "indexed",
        }

    def _node_architecture(self, state: PipelineState) -> Dict:
        """Analyze architecture."""
        report = self.architecture.analyze(state["repo_path"])
        file_tree = self.architecture.get_file_tree(state["repo_path"])
        return {
            "architecture_report": report.to_dict(),
            "file_tree": file_tree,
            "status": "architecture_done",
        }

    def _node_dependencies(self, state: PipelineState) -> Dict:
        """Build dependency graph."""
        self.dependency.build_graph(state["repo_path"])
        graph = self.dependency.get_import_graph()
        return {
            "dependency_graph": graph,
            "status": "dependencies_done",
        }

    def _node_documentation(self, state: PipelineState) -> Dict:
        """Generate documentation summaries."""
        summaries = self.documentation.summarize_all(state["repo_path"])
        return {
            "documentation_summaries": summaries,
            "status": "complete",
        }

    # ==================================================================
    # QUERY GRAPH
    # ==================================================================
    def _build_query_graph(self) -> StateGraph:
        g = StateGraph(PipelineState)

        g.add_node("route", self._node_route)
        g.add_node("retrieval_answer", self._node_retrieval_answer)
        g.add_node("architecture_answer", self._node_architecture_answer)
        g.add_node("dependency_answer", self._node_dependency_answer)
        g.add_node("documentation_answer", self._node_documentation_answer)

        g.set_entry_point("route")

        g.add_conditional_edges(
            "route",
            self._route_decision,
            {
                "code_search": "retrieval_answer",
                "architecture": "architecture_answer",
                "dependency": "dependency_answer",
                "documentation": "documentation_answer",
            },
        )

        g.add_edge("retrieval_answer", END)
        g.add_edge("architecture_answer", END)
        g.add_edge("dependency_answer", END)
        g.add_edge("documentation_answer", END)

        return g.compile()

    def _node_route(self, state: PipelineState) -> Dict:
        """Classify the question and decide which agent to use."""
        question = state["question"]
        route = self.router.classify(question)
        print(f"[Pipeline] Routed '{question[:60]}...' → {route}")
        return {"route": route}

    @staticmethod
    def _route_decision(state: PipelineState) -> str:
        route = state.get("route", "code_search")
        if route in ("code_search", "architecture", "dependency", "documentation"):
            return route
        return "code_search"

    def _node_retrieval_answer(self, state: PipelineState) -> Dict:
        result = self.retrieval.answer_question(state["question"])
        return {
            "answer": result["answer"],
            "sources": result["sources"],
            "agent_used": "retrieval",
        }

    def _node_architecture_answer(self, state: PipelineState) -> Dict:
        report = self.architecture.analyze(state.get("repo_path", "."))
        return {
            "answer": report.summary,
            "sources": [],
            "agent_used": "architecture",
        }

    def _node_dependency_answer(self, state: PipelineState) -> Dict:
        result = self.dependency.answer_question(state["question"])
        return {
            "answer": result["answer"],
            "sources": [],
            "agent_used": "dependency",
        }

    def _node_documentation_answer(self, state: PipelineState) -> Dict:
        result = self.documentation.answer_question(state["question"])
        return {
            "answer": result["answer"],
            "sources": result.get("sources", []),
            "agent_used": "documentation",
        }

    # ==================================================================
    # Public API
    # ==================================================================
    def ingest(self, repo_url: str = "", repo_path: str = "") -> Dict:
        """Run the full ingestion pipeline."""
        result = self._ingest_graph.invoke({
            "repo_url": repo_url,
            "repo_path": repo_path,
        })
        return dict(result)

    def ask(self, question: str, repo_path: str = ".") -> Dict:
        """Ask a question about the indexed codebase."""
        # Make sure we have an index loaded
        if self.retrieval.vectorstore is None:
            try:
                self.retrieval.load_existing_index()
            except Exception:
                pass

        result = self._query_graph.invoke({
            "question": question,
            "repo_path": repo_path,
        })
        return {
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
            "agent_used": result.get("agent_used", ""),
            "route": result.get("route", ""),
        }


# ------------------------------------------------------------------
# Convenience function
# ------------------------------------------------------------------
def run_pipeline(repo_url: str):
    """One-shot: ingest a repo and ask sample questions."""
    pipeline = CodebasePipeline()

    print("=" * 60)
    print(f"INGESTING: {repo_url}")
    print("=" * 60)
    result = pipeline.ingest(repo_url=repo_url)
    print(f"\nIngestion complete — {result.get('file_count', '?')} files, "
          f"{result.get('chunk_count', '?')} chunks")

    print("\n" + "=" * 60)
    print("ASKING SAMPLE QUESTIONS")
    print("=" * 60)

    questions = [
        "How does authentication work?",
        "What is the overall architecture of this project?",
        "What are the main dependencies?",
        "Give me a summary of the key files.",
    ]

    for q in questions:
        print(f"\nQ: {q}")
        ans = pipeline.ask(q, repo_path=result.get("repo_path", "."))
        print(f"A: {ans['answer'][:300]}...")
        print(f"   Agent: {ans['agent_used']} | Sources: {ans['sources'][:3]}")
        print("-" * 40)


if __name__ == "__main__":
    # Test on the current project
    pipeline = CodebasePipeline()
    result = pipeline.ingest(repo_path=".")
    print(f"\nIngested: {result.get('file_count')} files, {result.get('chunk_count')} chunks")

    ans = pipeline.ask("How does the retrieval agent work?", repo_path=".")
    print(f"\nAnswer: {ans['answer'][:500]}")
