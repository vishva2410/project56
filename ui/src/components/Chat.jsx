// ui/src/components/Chat.jsx
import { useState, useRef, useEffect } from "react";
import SourceCitation from "./SourceCitation";

export default function Chat({ messages, onSend, loading }) {
  const [input, setInput] = useState("");
  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;
    onSend(input.trim());
    setInput("");
  };

  const handleSuggestion = (text) => {
    if (loading) return;
    onSend(text);
  };

  const suggestions = [
    "How does authentication work?",
    "What is the project architecture?",
    "What are the main dependencies?",
    "Summarize the key files",
  ];

  return (
    <>
      {/* Chat messages */}
      <div className="chat-area">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <div className="icon">🧠</div>
            <h3>Codebase AI</h3>
            <p>
              Index a GitHub repo, then ask questions about its code,
              architecture, dependencies, and more.
            </p>
            <div className="suggestions">
              {suggestions.map((s, i) => (
                <button key={i} className="suggestion-chip" onClick={() => handleSuggestion(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className={`message message-${msg.role}`}>
              <div className="message-avatar">
                {msg.role === "user" ? "👤" : "🤖"}
              </div>
              <div>
                <div className="message-body">
                  {msg.content}
                </div>
                {msg.role === "ai" && (
                  <div className="message-meta">
                    {msg.agent_used && (
                      <span className="agent-badge">🔧 {msg.agent_used}</span>
                    )}
                    {msg.route && (
                      <span className="agent-badge">🛤️ {msg.route}</span>
                    )}
                  </div>
                )}
                {msg.role === "ai" && msg.sources && (
                  <SourceCitation sources={msg.sources} />
                )}
              </div>
            </div>
          ))
        )}

        {loading && (
          <div className="message message-ai">
            <div className="message-avatar">🤖</div>
            <div className="message-body">
              <div className="typing-indicator">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      {/* Chat input */}
      <div className="chat-input-area">
        <form className="chat-input-group" onSubmit={handleSubmit}>
          <input
            id="chat-input"
            className="chat-input"
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about the codebase..."
            disabled={loading}
            autoComplete="off"
          />
          <button
            id="send-button"
            className="btn-send"
            type="submit"
            disabled={!input.trim() || loading}
          >
            ➤
          </button>
        </form>
      </div>
    </>
  );
}
