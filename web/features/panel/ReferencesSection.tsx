import { Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { copy } from "@/core/config";
import type { PanelState } from "@/core/contract";
import {
  CopyButton,
  OUTLINED_BUTTON,
  ReceiptIcon,
  Section,
} from "@/features/panel/panel-ui";
import {
  formatClock,
  saveCopy,
  useCopy,
} from "@/features/panel/save-copy";

export function ReferencesSection({ panel }: { panel: PanelState }) {
  const { copiedId, handleCopy } = useCopy();
  const references = panel.receipts
    .filter((receipt) => receipt.kind !== "handoff")
    .reverse();

  return (
    <Section title={copy.panel.referencesTitle}>
      {references.length === 0 ? (
        <p className="text-[13px] leading-snug text-[var(--muted)]">
          {copy.panel.referencesEmpty}
        </p>
      ) : (
        <ul className="flex flex-col">
          {references.map((receipt) => (
            <li
              key={receipt.id}
              className="flex flex-col gap-1 border-b border-[var(--border)] py-3 first:pt-0 last:border-b-0"
            >
              <div className="flex items-start gap-2">
                <span className="mt-0.5">
                  <ReceiptIcon kind={receipt.kind} />
                </span>
                <span className="min-w-0 flex-1 text-[13px] leading-snug text-[var(--text)]">
                  {receipt.summary}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 pl-6">
                {receipt.reference ? (
                  <span className="min-w-0 truncate font-mono text-[12.5px] text-[var(--muted)]">
                    {receipt.reference}
                  </span>
                ) : (
                  <span />
                )}
                <div className="flex shrink-0 items-center gap-1">
                  <span className="text-[12px] text-[var(--muted)]">
                    {formatClock(receipt.at)}
                  </span>
                  {receipt.reference ? (
                    <CopyButton
                      value={receipt.reference}
                      label={copy.panel.copyReference}
                      copied={copiedId === receipt.id}
                      onCopy={(value) => handleCopy(value, receipt.id)}
                    />
                  ) : null}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        onClick={() => saveCopy(panel.receipts)}
        disabled={panel.receipts.length === 0}
        className={cn(OUTLINED_BUTTON, "mt-4 w-full")}
      >
        <Download size={15} aria-hidden="true" />
        {copy.panel.saveCopy}
      </button>
    </Section>
  );
}
