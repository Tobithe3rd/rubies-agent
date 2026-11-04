import { FileText } from "lucide-react";
import type { Citation } from "@/core/contract";
import { copy } from "@/core/config";

export function Sources({ citations }: { citations: Citation[] }) {
  const seen = new Set<string>();
  const unique = citations.filter((citation) => {
    const key = `${citation.document}\u0000${citation.section}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  if (unique.length === 0) return null;

  return (
    <div className="mt-3 border-t border-[var(--border)] pt-2.5">
      <p className="text-[12px] text-[var(--muted)]">{copy.chat.sources}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {unique.map((citation) => (
          <span
            key={`${citation.document}-${citation.section}`}
            className="inline-flex items-center gap-1.5 rounded-full bg-[var(--avatar-bg)] px-2.5 py-1 text-[12.5px] leading-snug text-[var(--text)]"
          >
            <FileText
              size={14}
              className="shrink-0 text-[var(--muted)]"
              aria-hidden="true"
            />
            {citation.document}
            {citation.section ? (
              <span className="text-[var(--muted)]"> · {citation.section}</span>
            ) : null}
          </span>
        ))}
      </div>
    </div>
  );
}
