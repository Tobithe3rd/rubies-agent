import { copy } from "@/core/config";
import type { Receipt } from "@/core/contract";
import { CopyButton, Section } from "@/features/panel/panel-ui";
import { useCopy } from "@/features/panel/save-copy";

export function HandoffSection({ handoff }: { handoff: Receipt }) {
  const { copiedId, handleCopy } = useCopy();

  return (
    <Section title={copy.panel.handoffTitle}>
      <p className="text-[14px] font-medium text-[var(--text)]">
        {copy.panel.handoffBody}
      </p>
      {handoff.reference ? (
        <div className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-[var(--border)] px-2.5 py-1.5">
          <span className="min-w-0 truncate font-mono text-[12.5px] text-[var(--text)]">
            {handoff.reference}
          </span>
          <CopyButton
            value={handoff.reference}
            label={copy.panel.copyTicket}
            copied={copiedId === handoff.id}
            onCopy={(value) => handleCopy(value, handoff.id)}
          />
        </div>
      ) : null}
      <div className="mt-3 rounded-lg bg-[var(--avatar-bg)] px-3 py-2.5">
        <p className="text-[12px] font-semibold uppercase tracking-[0.06em] text-[var(--muted)]">
          {copy.panel.sharedWithAgent}
        </p>
        <p className="mt-1.5 text-[13px] leading-snug text-[var(--text)]">
          {handoff.summary}
        </p>
      </div>
    </Section>
  );
}
