// ui/src/components/SourceCitation.jsx

export default function SourceCitation({ sources }) {
  if (!sources || sources.length === 0) return null;

  return (
    <div className="source-citations">
      {sources.map((src, i) => (
        <span key={i} className="source-chip" title={src}>
          📎 {src.split("/").pop()}
        </span>
      ))}
    </div>
  );
}
