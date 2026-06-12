# main.py
"""
Codebase AI — FastAPI application entrypoint.

Run with:
    python main.py             (dev server on port 8000)
    uvicorn main:app --reload  (alternative)
"""

from dotenv import load_dotenv
import os
from contextlib import asynccontextmanager

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from api.routes import router as api_router


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("⚠️  WARNING: GEMINI_API_KEY not set in .env — LLM calls will fail")
    else:
        print(f"✅ Gemini API key loaded: {api_key[:8]}...")
    print("🚀 Codebase AI is running — docs at http://localhost:8000/docs")
    yield


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Codebase AI",
    description="Multi-Agent Codebase Understanding System",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow the React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(api_router, prefix="/api")


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "name": "Codebase AI",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": ["/api/upload-repo", "/api/ask", "/api/health"],
    }


# ---------------------------------------------------------------------------
# Dev server
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)