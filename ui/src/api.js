// ui/src/api.js
/**
 * API client for the Codebase AI backend.
 */

const API_BASE = "http://localhost:8000/api";

export async function uploadRepo(githubUrl) {
  const res = await fetch(`${API_BASE}/upload-repo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ github_url: githubUrl }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Upload failed (${res.status})`);
  }
  return res.json();
}

export async function askQuestion(question, repoId = "") {
  const res = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, repo_id: repoId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Query failed (${res.status})`);
  }
  return res.json();
}

export async function getRepoTree(repoId) {
  const res = await fetch(`${API_BASE}/repo/${repoId}/tree`);
  if (!res.ok) throw new Error(`Failed to load tree (${res.status})`);
  return res.json();
}

export async function healthCheck() {
  const res = await fetch(`${API_BASE}/health`);
  return res.json();
}
