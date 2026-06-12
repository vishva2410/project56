// ui/src/components/FileTree.jsx
import { useState } from "react";

function TreeNode({ node, depth = 0 }) {
  const [expanded, setExpanded] = useState(depth < 2);

  if (!node) return null;

  const isDir = node.type === "directory";
  const icon = isDir ? (expanded ? "📂" : "📁") : getFileIcon(node.name);

  return (
    <div className="tree-node">
      <div
        className="tree-item"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => isDir && setExpanded(!expanded)}
      >
        <span className="tree-icon">{icon}</span>
        <span className="tree-label">{node.name}</span>
      </div>
      {isDir && expanded && node.children && (
        <div className="tree-children">
          {node.children.map((child, i) => (
            <TreeNode key={`${child.name}-${i}`} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function getFileIcon(name) {
  if (!name) return "📄";
  const ext = name.split(".").pop().toLowerCase();
  const icons = {
    py: "🐍", js: "🟨", jsx: "⚛️", ts: "🔷", tsx: "⚛️",
    json: "📋", yaml: "📋", yml: "📋", toml: "📋",
    md: "📝", txt: "📝", rst: "📝",
    html: "🌐", css: "🎨", scss: "🎨",
    sql: "🗃️", sh: "⚙️", bash: "⚙️",
    java: "☕", go: "🐹", rs: "🦀", rb: "💎",
  };
  return icons[ext] || "📄";
}

export default function FileTree({ tree }) {
  if (!tree || !tree.children || tree.children.length === 0) {
    return (
      <div style={{ color: "var(--text-muted)", fontSize: "13px", textAlign: "center", padding: "20px" }}>
        No repo indexed yet. Paste a GitHub URL above to get started.
      </div>
    );
  }

  return (
    <div className="file-tree">
      <TreeNode node={tree} />
    </div>
  );
}
