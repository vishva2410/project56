# rag/chunking.py
"""
Code-aware chunking strategy.

Splits by function / class boundaries (using AST output from CodeParser)
rather than by raw token count.  Falls back to RecursiveCharacterTextSplitter
for chunks that are still too large.
"""

from typing import Dict, List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


# Maximum chunk size (characters) before we force a secondary split
MAX_CHUNK_SIZE = 1500
CHUNK_OVERLAP = 100


class CodeChunker:
    """Convert raw code chunks (from CodeParser) into LangChain Documents."""

    def __init__(
        self,
        max_chunk_size: int = MAX_CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
    ):
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap

        # Fallback splitter for oversized chunks
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\ndef ", "\nclass ", "\n\n", "\n", " "],
        )

    def chunks_to_documents(self, raw_chunks: List[Dict]) -> List[Document]:
        """Convert CodeParser output into LangChain Document objects.

        Small chunks become a single Document.
        Large chunks are sub-split using RecursiveCharacterTextSplitter
        while preserving metadata.
        """
        documents: List[Document] = []

        for chunk in raw_chunks:
            content = chunk["content"]
            metadata = {
                "source": chunk.get("source", "unknown"),
                "module": chunk.get("module", "unknown"),
                "language": chunk.get("language", "python"),
                "chunk_type": chunk.get("chunk_type", "file"),
                "name": chunk.get("name", ""),
                "start_line": chunk.get("start_line", 0),
                "end_line": chunk.get("end_line", 0),
                "docstring": chunk.get("docstring", ""),
            }

            if len(content) <= self.max_chunk_size:
                documents.append(Document(page_content=content, metadata=metadata))
            else:
                # Sub-split but keep the same metadata on every piece
                sub_docs = self._splitter.create_documents(
                    texts=[content],
                    metadatas=[metadata],
                )
                documents.extend(sub_docs)

        print(f"[CodeChunker] Produced {len(documents)} documents from {len(raw_chunks)} raw chunks")
        return documents
