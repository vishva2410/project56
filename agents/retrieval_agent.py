# agents/retrieval_agent.py
"""
Retrieval Agent — embeds code chunks into ChromaDB and answers
questions using vector-similarity search + Gemini.
"""

from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from typing import Dict, List, Any, Optional

from agents.base import get_llm, get_embeddings, get_parser
from rag.code_parser import CodeParser
from rag.chunking import CodeChunker

load_dotenv()


class RetrievalAgent:
    """Vector-based code search over an indexed codebase."""

    def __init__(self, persist_dir: str = "./chroma_db"):
        self.embeddings = get_embeddings()
        self.persist_dir = persist_dir
        self.vectorstore: Optional[Chroma] = None
        self.llm = get_llm()
        self.parser = get_parser()

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    def index_codebase(self, code_chunks: List[Dict[str, Any]]):
        """Index pre-parsed code chunks (legacy interface)."""
        print(f"[RetrievalAgent] Indexing {len(code_chunks)} code chunks...")
        documents = []
        for chunk in code_chunks:
            doc = Document(
                page_content=chunk["content"],
                metadata={
                    "source": chunk.get("source", "unknown"),
                    "module": chunk.get("module", "unknown"),
                    "language": chunk.get("language", "python"),
                    "chunk_type": chunk.get("chunk_type", "file"),
                    "name": chunk.get("name", ""),
                },
            )
            documents.append(doc)

        self.vectorstore = Chroma.from_documents(
            documents=documents,
            embedding=self.embeddings,
            persist_directory=self.persist_dir,
        )
        print(f"[RetrievalAgent] Indexed {len(documents)} chunks into ChromaDB")

    def index_from_repo(self, repo_path: str):
        """Parse a local repo, chunk it, and index into ChromaDB."""
        parser = CodeParser()
        raw_chunks = parser.parse_repo(repo_path)

        chunker = CodeChunker()
        documents = chunker.chunks_to_documents(raw_chunks)

        print(f"[RetrievalAgent] Storing {len(documents)} documents in ChromaDB...")
        self.vectorstore = Chroma.from_documents(
            documents=documents,
            embedding=self.embeddings,
            persist_directory=self.persist_dir,
        )
        print(f"[RetrievalAgent] Indexing complete — {len(documents)} documents stored")

    def index_documents(self, documents: List[Document]):
        """Index a list of pre-built LangChain Documents."""
        print(f"[RetrievalAgent] Storing {len(documents)} documents...")
        self.vectorstore = Chroma.from_documents(
            documents=documents,
            embedding=self.embeddings,
            persist_directory=self.persist_dir,
        )

    def load_existing_index(self):
        """Load a previously persisted ChromaDB index."""
        self.vectorstore = Chroma(
            persist_directory=self.persist_dir,
            embedding_function=self.embeddings,
        )
        count = self.vectorstore._collection.count()
        print(f"[RetrievalAgent] Loaded index with {count} chunks")

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------
    def answer_question(
        self,
        question: str,
        module_filter: Optional[str] = None,
        k: int = 4,
    ) -> Dict:
        """Answer a question using vector similarity search + LLM."""
        if not self.vectorstore:
            raise RuntimeError("No index loaded. Call index_from_repo() or load_existing_index() first.")

        search_kwargs: Dict[str, Any] = {"k": k}
        if module_filter:
            search_kwargs["filter"] = {"module": module_filter}

        retriever = self.vectorstore.as_retriever(search_kwargs=search_kwargs)
        relevant_docs = retriever.invoke(question)

        context_parts = []
        sources = set()
        for doc in relevant_docs:
            source = doc.metadata.get("source", "unknown")
            sources.add(source)
            name = doc.metadata.get("name", "")
            header = f"# File: {source}"
            if name:
                header += f" | {name}"
            context_parts.append(f"{header}\n{doc.page_content}")

        context = "\n\n---\n\n".join(context_parts)

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert code analyst. Answer questions about the codebase "
             "using ONLY the provided code context. Be specific and reference "
             "function names, file names, and line logic. If the answer isn't in "
             "the context, clearly say so.\n\n"
             "Codebase context:\n{context}"),
            ("human", "{question}"),
        ])

        chain = prompt | self.llm | self.parser
        answer = chain.invoke({"context": context, "question": question})

        return {
            "answer": answer,
            "sources": list(sources),
            "chunks_used": len(relevant_docs),
        }

    def search(self, query: str, k: int = 4) -> List[Document]:
        """Raw vector search — returns matching Documents without LLM."""
        if not self.vectorstore:
            raise RuntimeError("No index loaded.")
        return self.vectorstore.similarity_search(query, k=k)


# ------------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------------
if __name__ == "__main__":
    agent = RetrievalAgent()
    agent.load_existing_index()

    questions = [
        "How does authentication work?",
        "Where is payment processing implemented?",
        "How is a JWT token validated?",
    ]

    for q in questions:
        print(f"\nQuestion: {q}")
        result = agent.answer_question(q)
        print(f"Answer: {result['answer']}")
        print(f"Sources: {result['sources']}")
        print("=" * 50)
