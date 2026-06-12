# agents/documentation_agent.py
"""
Documentation Agent — auto-summarizes each file in a codebase using
Gemini and stores the summaries for retrieval.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from agents.base import get_llm, get_embeddings, get_parser
from rag.code_parser import CodeParser, SKIP_DIRS, SUPPORTED_EXTENSIONS


class DocumentationAgent:
    """Generate and store per-file documentation summaries."""

    def __init__(self, cache_path: str = "./doc_cache.json"):
        self.llm = get_llm(temperature=0.2)
        self.parser = get_parser()
        self.embeddings = get_embeddings()
        self.cache_path = cache_path
        self._cache: Dict[str, str] = {}
        self._load_cache()

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------
    def _load_cache(self):
        if os.path.isfile(self.cache_path):
            try:
                self._cache = json.loads(Path(self.cache_path).read_text())
                print(f"[DocumentationAgent] Loaded {len(self._cache)} cached summaries")
            except Exception:
                self._cache = {}

    def _save_cache(self):
        Path(self.cache_path).write_text(json.dumps(self._cache, indent=2))

    # ------------------------------------------------------------------
    # Single-file summarization
    # ------------------------------------------------------------------
    def summarize_file(self, filepath: str, content: str) -> str:
        """Produce a concise summary of a single source file."""
        # Truncate very large files to avoid token limits
        if len(content) > 12000:
            content = content[:12000] + "\n\n... (truncated)"

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a senior developer writing internal documentation. "
             "Given a source file, produce a clear 3-5 sentence summary that "
             "covers: (1) what the file does, (2) key functions/classes it defines, "
             "(3) how it fits into the broader codebase. Be concise and technical."),
            ("human", "File: {filepath}\n\n```\n{content}\n```"),
        ])

        chain = prompt | self.llm | self.parser
        summary = chain.invoke({"filepath": filepath, "content": content})
        return summary

    # ------------------------------------------------------------------
    # Batch summarization
    # ------------------------------------------------------------------
    def summarize_all(self, repo_path: str, force: bool = False) -> Dict[str, str]:
        """Summarize every supported file in the repo.

        Results are cached to disk so re-runs are fast.  Pass force=True
        to regenerate all summaries.
        """
        repo_path = os.path.abspath(repo_path)
        summaries: Dict[str, str] = {}
        files_to_summarize: List[tuple] = []

        for dirpath, dirnames, filenames in os.walk(repo_path):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                fpath = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(fpath, repo_path)

                if not force and rel_path in self._cache:
                    summaries[rel_path] = self._cache[rel_path]
                    continue

                try:
                    content = Path(fpath).read_text(errors="replace")
                    if content.strip():
                        files_to_summarize.append((rel_path, content))
                except Exception:
                    continue

        # Summarize new files
        for i, (rel_path, content) in enumerate(files_to_summarize, 1):
            print(f"[DocumentationAgent] Summarizing ({i}/{len(files_to_summarize)}): {rel_path}")
            try:
                summary = self.summarize_file(rel_path, content)
                summaries[rel_path] = summary
                self._cache[rel_path] = summary
            except Exception as e:
                summaries[rel_path] = f"(Error summarizing: {e})"
                self._cache[rel_path] = summaries[rel_path]

        self._save_cache()
        print(f"[DocumentationAgent] {len(summaries)} file summaries ready")
        return summaries

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def get_summary(self, filepath: str) -> Optional[str]:
        """Get a cached summary for a file."""
        return self._cache.get(filepath)

    def get_all_summaries(self) -> Dict[str, str]:
        """Return all cached summaries."""
        return dict(self._cache)

    def as_documents(self) -> List[Document]:
        """Convert cached summaries into LangChain Documents for indexing."""
        docs = []
        for filepath, summary in self._cache.items():
            docs.append(Document(
                page_content=summary,
                metadata={
                    "source": filepath,
                    "chunk_type": "documentation",
                    "language": CodeParser._ext_to_language(Path(filepath).suffix.lower()),
                },
            ))
        return docs

    def answer_question(self, question: str) -> Dict:
        """Answer a documentation question using cached summaries."""
        if not self._cache:
            return {
                "answer": "No documentation summaries available. Run summarize_all() first.",
                "sources": [],
            }

        # Build a context string from all summaries
        context_parts = []
        for filepath, summary in list(self._cache.items())[:30]:  # cap to avoid token overflow
            context_parts.append(f"## {filepath}\n{summary}")

        context = "\n\n".join(context_parts)

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a codebase documentation expert. Answer questions using "
             "the file summaries provided below. Reference specific file names. "
             "If the answer isn't in the summaries, say so.\n\n"
             "File summaries:\n{context}"),
            ("human", "{question}"),
        ])

        chain = prompt | self.llm | self.parser
        answer = chain.invoke({"context": context, "question": question})

        return {
            "answer": answer,
            "sources": list(self._cache.keys())[:10],
        }


# ------------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------------
if __name__ == "__main__":
    agent = DocumentationAgent()
    summaries = agent.summarize_all(".")

    for filepath, summary in list(summaries.items())[:3]:
        print(f"\n{'=' * 50}")
        print(f"File: {filepath}")
        print(f"Summary: {summary}")
