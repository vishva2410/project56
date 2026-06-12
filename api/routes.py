# api/routes.py
"""
FastAPI routes for the Codebase AI system.

Endpoints:
  POST /upload-repo    — clone & index a GitHub repo
  POST /ask            — ask a question about the indexed codebase
  GET  /repo/{id}/tree — get the file tree of an indexed repo
  GET  /health         — health check
"""

import os
import traceback
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.pipeline import CodebasePipeline

router = APIRouter()

# ---------------------------------------------------------------------------
# Singleton pipeline instance (shared across requests)
# ---------------------------------------------------------------------------
_pipeline: Optional[CodebasePipeline] = None


def get_pipeline() -> CodebasePipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = CodebasePipeline()
    return _pipeline


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class UploadRepoRequest(BaseModel):
    github_url: str


class UploadRepoResponse(BaseModel):
    repo_id: str
    file_count: int
    chunk_count: int
    status: str
    architecture_summary: str = ""
    frameworks: list = []


class AskRequest(BaseModel):
    question: str
    repo_id: str = ""


class AskResponse(BaseModel):
    answer: str
    sources: list = []
    agent_used: str = ""
    route: str = ""


class HealthResponse(BaseModel):
    status: str
    indexed: bool
    repo_id: str = ""


# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------
_indexed_repos: dict = {}  # repo_id → { repo_path, file_tree, ... }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/upload-repo", response_model=UploadRepoResponse)
async def upload_repo(req: UploadRepoRequest):
    """Clone a GitHub repo, parse it, and index into the system."""
    try:
        pipeline = get_pipeline()
        result = pipeline.ingest(repo_url=req.github_url)

        repo_id = result.get("repo_id", "unknown")
        _indexed_repos[repo_id] = {
            "repo_path": result.get("repo_path", ""),
            "file_tree": result.get("file_tree", {}),
            "architecture_report": result.get("architecture_report", {}),
        }

        arch = result.get("architecture_report", {})

        return UploadRepoResponse(
            repo_id=repo_id,
            file_count=result.get("file_count", 0),
            chunk_count=result.get("chunk_count", 0),
            status="complete",
            architecture_summary=arch.get("summary", ""),
            frameworks=arch.get("frameworks", []),
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask", response_model=AskResponse)
async def ask_question(req: AskRequest):
    """Ask a question about the indexed codebase."""
    try:
        pipeline = get_pipeline()

        repo_path = "."
        if req.repo_id and req.repo_id in _indexed_repos:
            repo_path = _indexed_repos[req.repo_id].get("repo_path", ".")

        result = pipeline.ask(req.question, repo_path=repo_path)

        return AskResponse(
            answer=result.get("answer", ""),
            sources=result.get("sources", []),
            agent_used=result.get("agent_used", ""),
            route=result.get("route", ""),
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/repo/{repo_id}/tree")
async def get_repo_tree(repo_id: str):
    """Return the file tree of an indexed repo."""
    if repo_id not in _indexed_repos:
        raise HTTPException(status_code=404, detail=f"Repo '{repo_id}' not found")

    return _indexed_repos[repo_id].get("file_tree", {})


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    repo_ids = list(_indexed_repos.keys())
    return HealthResponse(
        status="healthy",
        indexed=len(repo_ids) > 0,
        repo_id=repo_ids[0] if repo_ids else "",
    )
