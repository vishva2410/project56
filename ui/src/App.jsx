// ui/src/App.jsx
import { useState } from "react";
import Chat from "./components/Chat";
import FileTree from "./components/FileTree";
import { uploadRepo, askQuestion } from "./api";
import "./App.css";

export default function App() {
  const [repoUrl, setRepoUrl] = useState("");
  const [repoId, setRepoId] = useState("");
  const [fileTree, setFileTree] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [status, setStatus] = useState(null); // { type, text }

  // ── Upload repo ──
  const handleUpload = async () => {
    if (!repoUrl.trim() || indexing) return;
    setIndexing(true);
    setStatus({ type: "loading", text: "Cloning & indexing repo..." });

    try {
      const result = await uploadRepo(repoUrl.trim());
      setRepoId(result.repo_id);
      setStatus({
        type: "success",
        text: `✅ Indexed ${result.file_count} files (${result.chunk_count} chunks)`,
      });

      // Load file tree
      if (result.repo_id) {
        try {
          const res = await fetch(`http://localhost:8000/api/repo/${result.repo_id}/tree`);
          const tree = await res.json();
          setFileTree(tree);
        } catch {
          // tree is optional
        }
      }

      // Add architecture summary as first message
      if (result.architecture_summary) {
        setMessages((prev) => [
          ...prev,
          {
            role: "ai",
            content: `📐 **Architecture Summary**\n\n${result.architecture_summary}${
              result.frameworks?.length
                ? `\n\n🛠️ Frameworks detected: ${result.frameworks.join(", ")}`
                : ""
            }`,
            agent_used: "architecture",
          },
        ]);
      }
    } catch (err) {
      setStatus({ type: "error", text: `❌ ${err.message}` });
    } finally {
      setIndexing(false);
    }
  };

  // ── Ask question ──
  const handleSend = async (question) => {
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setLoading(true);

    try {
      const result = await askQuestion(question, repoId);
      setMessages((prev) => [
        ...prev,
        {
          role: "ai",
          content: result.answer,
          sources: result.sources,
          agent_used: result.agent_used,
          route: result.route,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: "ai",
          content: `❌ Error: ${err.message}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h2>Repository</h2>
          <div className="repo-input-group">
            <input
              id="repo-url-input"
              className="repo-input"
              type="text"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/user/repo"
              onKeyDown={(e) => e.key === "Enter" && handleUpload()}
            />
            <button
              id="index-button"
              className="btn btn-primary"
              onClick={handleUpload}
              disabled={indexing || !repoUrl.trim()}
            >
              {indexing ? <span className="spinner" /> : "Index"}
            </button>
          </div>
          {status && (
            <div className={`sidebar-status status-${status.type}`}>
              {status.type === "loading" && <span className="spinner" />}
              {status.text}
            </div>
          )}
        </div>
        <div className="sidebar-content">
          <FileTree tree={fileTree} />
        </div>
      </aside>

      {/* Main */}
      <main className="main-content">
        <header className="main-header">
          <span className="logo">Codebase AI</span>
          <span className="subtitle">Multi-Agent Code Understanding</span>
        </header>
        <Chat messages={messages} onSend={handleSend} loading={loading} />
      </main>
    </div>
  );
}
