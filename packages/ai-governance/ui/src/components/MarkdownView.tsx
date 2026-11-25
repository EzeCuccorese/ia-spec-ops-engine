import React from "react";

interface MarkdownViewProps {
  text: string;
  onWikilinkClick?: (target: string) => void;
}

function renderInline(
  line: string,
  onWikilinkClick?: (target: string) => void
): React.ReactNode[] {
  const tokens = line.split(/(\[\[[^\]]+\]\]|`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)]+\))/g);
  return tokens.map((part, idx) => {
    if (part.startsWith("[[") && part.endsWith("]]")) {
      const target = part.slice(2, -2).trim();
      return (
        <button
          key={idx}
          type="button"
          className="wikilink-btn"
          onClick={() => onWikilinkClick?.(target)}
        >
          [[{target}]]
        </button>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={idx}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={idx}>{part.slice(2, -2)}</strong>;
    }
    const linkMatch = /^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/.exec(part);
    if (linkMatch) {
      return (
        <a key={idx} href={linkMatch[2]} target="_blank" rel="noreferrer">
          {linkMatch[1]}
        </a>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
}

export function MarkdownView({ text, onWikilinkClick }: MarkdownViewProps) {
  const lines = text.split(/\r?\n/);
  const blocks: React.ReactNode[] = [];
  let inCode = false;
  let codeLines: string[] = [];

  lines.forEach((line, idx) => {
    if (line.trim().startsWith("```")) {
      if (inCode) {
        blocks.push(
          <pre key={`code-${idx}`}>
            <code>{codeLines.join("\n")}</code>
          </pre>
        );
        codeLines = [];
        inCode = false;
      } else {
        inCode = true;
      }
      return;
    }
    if (inCode) {
      codeLines.push(line);
      return;
    }
    if (line.startsWith("### ")) {
      blocks.push(<h3 key={idx}>{renderInline(line.slice(4), onWikilinkClick)}</h3>);
    } else if (line.startsWith("## ")) {
      blocks.push(<h2 key={idx}>{renderInline(line.slice(3), onWikilinkClick)}</h2>);
    } else if (line.startsWith("# ")) {
      blocks.push(<h1 key={idx}>{renderInline(line.slice(2), onWikilinkClick)}</h1>);
    } else if (line.trim().startsWith("- ") || line.trim().startsWith("* ")) {
      blocks.push(
        <div key={idx} style={{ paddingLeft: "0.9rem", margin: "0.2rem 0" }}>
          • {renderInline(line.trim().slice(2), onWikilinkClick)}
        </div>
      );
    } else if (line.trim()) {
      blocks.push(<p key={idx}>{renderInline(line, onWikilinkClick)}</p>);
    }
  });

  return <div className="markdown-body">{blocks}</div>;
}
