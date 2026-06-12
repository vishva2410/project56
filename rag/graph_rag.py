# rag/graph_rag.py
"""
Graph RAG — hybrid retrieval that combines:
  1. ChromaDB vector search (semantic similarity)
  2. Dependency graph enrichment (structural context from Neo4j/networkx)

The idea: when you find relevant code via embeddings, also pull in the
files that import/are imported by those files for richer context.
"""

from typing import Dict, List, Optional

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from agents.base import get_llm, get_parser
from agents.retrieval_agent import RetrievalAgent
from agents.dependency_agent import DependencyAgent


class GraphRAG:
    """Hybrid vector + graph retrieval."""

    def __init__(
        self,
        retrieval_agent: RetrievalAgent,
        dependency_agent: DependencyAgent,
        enrichment_depth: int = 1,
    ):
        self.retrieval = retrieval_agent
        self.dependency = dependency_agent
        self.enrichment_depth = enrichment_depth
        self.llm = get_llm()
        self.parser = get_parser()

    def retrieve_and_enrich(self, query: str, k: int = 4) -> Dict:
        """
        1. Vector search for top-k documents
        2. For each result, look up its dependencies and dependents
        3. Pull in related code chunks
        4. Return the enriched context
        """
        # Step 1: Vector search
        base_docs = self.retrieval.search(query, k=k)

        if not base_docs:
            return {
                "documents": [],
                "enriched_context": "",
                "graph_connections": [],
            }

        # Step 2: Gather graph context for each result
        source_files = set()
        for doc in base_docs:
            src = doc.metadata.get("source", "")
            if src:
                source_files.add(src)

        graph_connections = []
        related_files = set()

        for src in source_files:
            # What does this file import?
            deps = self.dependency.query_dependencies(src)
            for dep in deps:
                graph_connections.append({"from": src, "rel": "IMPORTS", "to": dep})
                related_files.add(dep)

            # What imports this file?
            dependents = self.dependency.query_dependents(src)
            for dep in dependents:
                graph_connections.append({"from": dep, "rel": "IMPORTS", "to": src})
                related_files.add(dep)

        # Step 3: Pull in related code from ChromaDB
        enrichment_docs = []
        for related in related_files - source_files:
            try:
                related_results = self.retrieval.search(related, k=2)
                enrichment_docs.extend(related_results)
            except Exception:
                pass

        # Step 4: Build enriched context
        all_docs = base_docs + enrichment_docs[:6]  # cap enrichment

        context_parts = []
        for doc in all_docs:
            source = doc.metadata.get("source", "unknown")
            name = doc.metadata.get("name", "")
            header = f"# File: {source}"
            if name:
                header += f" | {name}"
            context_parts.append(f"{header}\n{doc.page_content}")

        # Add graph relationship context
        if graph_connections:
            rel_text = "\n".join(
                f"  {c['from']} --{c['rel']}--> {c['to']}"
                for c in graph_connections[:15]
            )
            context_parts.append(f"# Dependency Relationships\n{rel_text}")

        enriched_context = "\n\n---\n\n".join(context_parts)

        return {
            "documents": all_docs,
            "enriched_context": enriched_context,
            "graph_connections": graph_connections,
        }

    def answer(self, question: str, k: int = 4) -> Dict:
        """Full Graph RAG: retrieve + enrich + answer with LLM."""
        enriched = self.retrieve_and_enrich(question, k=k)

        if not enriched["enriched_context"]:
            return {
                "answer": "No relevant code found in the index.",
                "sources": [],
                "connections": [],
            }

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert code analyst with access to both code snippets "
             "and dependency graph data. Answer the question using ALL the "
             "provided context — both the code and the dependency relationships. "
             "Be specific about which files and functions are involved and how "
             "they connect to each other.\n\n"
             "Context:\n{context}"),
            ("human", "{question}"),
        ])

        chain = prompt | self.llm | self.parser
        answer = chain.invoke({
            "context": enriched["enriched_context"],
            "question": question,
        })

        sources = list(set(
            doc.metadata.get("source", "unknown")
            for doc in enriched["documents"]
        ))

        return {
            "answer": answer,
            "sources": sources,
            "connections": enriched["graph_connections"],
        }
