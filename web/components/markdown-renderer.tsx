import ReactMarkdown from "react-markdown";

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <ReactMarkdown
      components={{
        p: ({ children }) => <p className="mb-3 leading-relaxed">{children}</p>,
        strong: ({ children }) => <strong className="font-bold text-foreground">{children}</strong>,
        ul: ({ children }) => <ul className="list-disc pl-5 mb-3 space-y-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-5 mb-3 space-y-1">{children}</ol>,
        li: ({ children }) => <li className="mb-1">{children}</li>,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}
