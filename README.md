# 🧠 Codebase AI — Multi-Agent Code Understanding System

A multi-agent system that **clones, parses, indexes, and understands** any GitHub codebase.  
Ask natural-language questions and get answers backed by code — powered by **Gemini**, **LangGraph**, **ChromaDB**, and **Neo4j**.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     React Frontend (Vite)                   │
│   ┌──────────┐   ┌──────────────────────────────────────┐   │
│   │ File Tree│   │            Chat Interface             │   │
│   │  Panel   │   │  Question → Answer + Source Citations │   │
│   └──────────┘   └──────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP (port 5173 → 8000)
┌──────────────────────────▼──────────────────────────────────┐
│                  FastAPI Backend (Python)                    │
│   POST /api/upload-repo    POST /api/ask                    │
│   GET  /api/repo/{id}/tree GET  /api/health                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│              LangGraph Pipeline (agents/pipeline.py)         │
│                                                              │
│   ┌─────────┐    ┌────────────┐    ┌───────────────┐        │
│   │ Question │───▶│  Router    │───▶│  Agent Dispatch│       │
│   │         │    │(Gemini LLM)│    │               │        │
│   └─────────┘    └────────────┘    └───────┬───────┘        │
│                                            │                 │
│          ┌─────────────┬──────────────┬────┘                 │
│          ▼             ▼              ▼                       │
│   ┌────────────┐ ┌──────────┐ ┌────────────┐                │
│   │ Retrieval  │ │Dependency│ │Architecture│                 │
│   │   Agent    │ │  Agent   │ │   Agent    │                 │
│   └──────┬─────┘ └────┬─────┘ └────────────┘                │
│          │             │                                     │
│          ▼             ▼                                     │
│   ┌────────────┐ ┌──────────┐        ┌──────────────┐       │
│   │  ChromaDB  │ │  Neo4j / │        │Documentation │       │
│   │  (Vectors) │ │ NetworkX │        │    Agent     │       │
│   └────────────┘ └──────────┘        └──────────────┘       │
└──────────────────────────────────────────────────────────────┘
```

---

## 📂 Project Structure — File-by-File Explanation

### Root Files

| File | Purpose |
|------|---------|
| `main.py` | **FastAPI app entrypoint.** Creates the app, mounts CORS middleware, includes API routes, validates the Gemini API key on startup, and runs the uvicorn dev server. |
| `requirements.txt` | All Python dependencies: LangChain, LangGraph, ChromaDB, Neo4j, FastAPI, GitPython, Gemini SDK. |
| `.env` | Stores `GEMINI_API_KEY` (and optionally `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`). |
| `Dockerfile` | Multi-stage build: builds React frontend with Node.js, then layers Python backend on top. |
| `docker-compose.yml` | Orchestrates 2 services: the app and Neo4j, with persistent volumes for ChromaDB and cloned repos. |
| `day2_practice.py` | Learning exercise — LangChain prompt chain with Gemini (kept for reference). |
| `day3_rag.py` | Learning exercise — basic RAG pipeline with ChromaDB (kept for reference). |

---

### `rag/` — Retrieval-Augmented Generation Layer

| File | Purpose |
|------|---------|
| `code_parser.py` | **Git clone + AST parsing engine.** Clones repos via GitPython, walks the file tree, and uses Python's `ast` module to extract functions, classes, methods, and module-level code. Produces structured chunks with rich metadata (source path, module name, language, line numbers, docstrings). Non-Python files are stored as single whole-file chunks. |
| `chunking.py` | **Code-aware chunker.** Converts raw parser output into LangChain `Document` objects. Small chunks (< 1500 chars) become one document. Large chunks are sub-split using `RecursiveCharacterTextSplitter` while preserving all metadata. |
| `graph_rag.py` | **Hybrid retrieval (Graph RAG).** Combines ChromaDB vector search with dependency graph enrichment. When you find relevant code via embeddings, it also pulls in files that import/are imported by those files, giving the LLM richer context about how code connects. |

---

### `agents/` — The Four Core Agents + Orchestration

| File | Purpose |
|------|---------|
| `base.py` | **Shared LLM factories.** `get_llm()` returns a `ChatGoogleGenerativeAI` (Gemini 1.5 Flash), `get_embeddings()` returns `GoogleGenerativeAIEmbeddings`, `get_parser()` returns a `StrOutputParser`. Every agent imports from here — change the model in one place. |
| `retrieval_agent.py` | **Vector search agent.** Indexes code chunks into ChromaDB and answers questions via similarity search + Gemini. Supports: `index_from_repo()` (parse + index a local repo), `index_documents()` (index pre-built docs), `answer_question()` (search + LLM answer), `search()` (raw vector search without LLM). |
| `architecture_agent.py` | **Structure analyzer.** Walks the repo to detect frameworks (Flask, FastAPI, Django, React, Express, etc.), architectural patterns (MVC, service layer, monorepo, clean architecture), count languages/files/lines, find entry points, and generate a Gemini-powered architecture summary. |
| `dependency_agent.py` | **Import graph agent.** Parses every `.py` file's `import` statements using `ast`, builds a dependency graph with `IMPORTS` and `DEFINES` relationships. Dual backend: **Neo4j** (if configured) or **networkx** (zero-setup fallback). Answers "what depends on X?" and "what does X depend on?" queries. |
| `documentation_agent.py` | **File summarizer.** Auto-summarizes every file in a repo using Gemini, caches results to `doc_cache.json` for fast re-runs. Provides `answer_question()` to answer documentation questions using cached summaries. |
| `router.py` | **Question classifier.** Uses a few-shot Gemini prompt to classify questions into: `code_search`, `architecture`, `dependency`, `documentation`, or `multi_hop`. Routes to the appropriate agent. |
| `multi_hop.py` | **Complex reasoning chain.** For questions that span multiple files or concepts. Decomposes the question into 2-4 sub-questions, runs each through retrieval + dependency agents, then synthesizes a coherent final answer. Implemented as a LangGraph sub-graph. |
| `pipeline.py` | **LangGraph orchestrator.** Two compiled graphs: (1) **Ingest graph**: clone → parse → index → analyze architecture → build deps → generate docs. (2) **Query graph**: classify question → route → dispatch to right agent → return answer. This is the main entry point for the system. |

---

### `api/` — FastAPI Backend

| File | Purpose |
|------|---------|
| `routes.py` | **HTTP endpoints.** `POST /api/upload-repo` accepts a GitHub URL, runs the full ingestion pipeline, returns file/chunk counts + architecture summary. `POST /api/ask` accepts a question, routes it through the pipeline, returns the answer + source citations + agent used. `GET /api/repo/{id}/tree` returns the file tree JSON. `GET /api/health` returns system status. |

---

### `ui/` — React Frontend (Vite)

| File | Purpose |
|------|---------|
| `src/App.jsx` | **Main layout.** Sidebar (repo URL input + file tree) + main area (header + chat). Manages state for repo indexing, message history, and loading states. |
| `src/components/Chat.jsx` | **Chat interface.** Renders message bubbles (user + AI), typing indicator animation, suggestion chips for first-time users, and the chat input with send button. |
| `src/components/FileTree.jsx` | **File tree panel.** Recursive collapsible tree with file-type emoji icons. Auto-expands the first 2 levels. |
| `src/components/SourceCitation.jsx` | **Source chips.** Renders clickable file references below each AI answer showing which files were used. |
| `src/api.js` | **API client.** Fetch wrappers for `uploadRepo()`, `askQuestion()`, `getRepoTree()`, `healthCheck()`. |
| `src/index.css` | **Design system.** Dark theme with Inter/JetBrains Mono fonts, purple gradient accents, glassmorphism cards, smooth animations, custom scrollbar. |

---

### `tests/` — Test Suite

| File | Purpose |
|------|---------|
| `test_code_parser.py` | Tests AST parsing, metadata extraction, file tree generation, docstring extraction, non-Python file handling. |
| `test_agents.py` | Smoke tests for CodeChunker and DependencyAgent (networkx backend). No API key needed. |
| `test_api.py` | Tests FastAPI endpoints: root, health, and 404 handling. |

---

### `data/` — Test Data

| File | Purpose |
|------|---------|
| `sample_code.py` | A realistic auth + payment stub (JWT, password hashing, user registration, payment processing) used by `day3_rag.py` for RAG testing. |

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.11+
- Node.js 18+
- A [Gemini API key](https://aistudio.google.com) (free)

### 2. Setup

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/project56.git
cd project56

# Python
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# React frontend
cd ui
npm install
cd ..
```

### 3. Run

```bash
# Terminal 1 — Backend
source venv/bin/activate
python main.py
# → http://localhost:8000 (API docs at /docs)

# Terminal 2 — Frontend
cd ui
npm run dev
# → http://localhost:5173
```

### 4. Use

1. Paste a GitHub URL in the sidebar → click **Index**
2. Wait for ingestion (cloning, parsing, embedding, analysis)
3. Ask questions in the chat

---

## 🐳 Docker

```bash
docker-compose up --build
# App: http://localhost:8000
# Neo4j Browser: http://localhost:7474
```

---

## 🧪 Tests

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

---

## 🔑 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | ✅ | — | Google AI Studio API key |
| `NEO4J_URI` | ❌ | — | Neo4j connection URI (e.g. `bolt://localhost:7687`) |
| `NEO4J_USER` | ❌ | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | ❌ | — | Neo4j password |

> **Note:** Neo4j is optional. Without it, the Dependency Agent falls back to an in-memory networkx graph. All other features work identically.

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM | Gemini 1.5 Flash (via `langchain-google-genai`) |
| Embeddings | Google `embedding-001` |
| Agent Framework | LangGraph |
| Vector Store | ChromaDB |
| Graph DB | Neo4j (optional, networkx fallback) |
| Code Parsing | Python `ast` module + GitPython |
| Backend | FastAPI + Uvicorn |
| Frontend | React + Vite |
| Containerization | Docker + Docker Compose |
