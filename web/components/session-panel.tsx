"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Check,
  Copy,
  CreditCard,
  Download,
  FileText,
  Headphones,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { SessionPanel as Panel, SessionReceipt } from "@/lib/stream";

const SECTION_TITLE =
  "text-[12px] font-semibold uppercase tracking-[0.06em] text-[var(--muted)]";

const OUTLINED_BUTTON =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-[var(--input-border)] bg-[var(--surface)] px-3 text-[13px] font-medium text-[var(--text)] transition-colors hover:bg-[var(--avatar-bg)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-9";

const ICON_BUTTON =
  "inline-flex size-11 shrink-0 items-center justify-center rounded-lg text-[var(--muted)] transition-colors hover:bg-[var(--avatar-bg)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] sm:size-9";

const COMMON_TASKS: Array<{ label: string; message: string }> = [
  { label: "Block a lost card", message: "I lost my card, please block it" },
  {
    label: "Report a failed or double debit",
    message: "I think a transfer failed or I was debited twice",
  },
  {
    label: "Check loan eligibility",
    message: "Can I check if I qualify for a loan?",
  },
  { label: "Talk to a person", message: "I want to speak to a human agent" },
];

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);

  return matches;
}

function useCountdown(receivedAt: number | null, seconds: number | null) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (receivedAt === null || seconds === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [receivedAt, seconds]);

  if (receivedAt === null || seconds === null) return null;
  return Math.max(0, Math.floor(seconds - (now - receivedAt) / 1000));
}

function formatClock(at: string): string {
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-NG", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function ReceiptIcon({ kind }: { kind: SessionReceipt["kind"] }) {
  if (kind === "card_block") {
    return <CreditCard size={14} className="shrink-0 text-[var(--muted)]" />;
  }
  if (kind === "handoff") {
    return <Headphones size={14} className="shrink-0 text-[var(--muted)]" />;
  }
  return <FileText size={14} className="shrink-0 text-[var(--muted)]" />;
}

function CopyButton({
  value,
  label,
  copied,
  onCopy,
}: {
  value: string;
  label: string;
  copied: boolean;
  onCopy: (value: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onCopy(value)}
      className="inline-flex min-h-11 shrink-0 items-center gap-1 rounded-md px-2 text-[12px] font-medium text-[var(--muted)] transition-colors hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] sm:min-h-7"
      aria-label={`Copy ${label}`}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function Section({
  title,
  children,
  className,
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("border-b border-[var(--border)] px-4 py-4", className)}>
      <h2 className={SECTION_TITLE}>{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export interface SessionPanelProps {
  panel: Panel;
  receivedAt: number | null;
  open: boolean;
  onClose: () => void;
  onEndChat: () => void;
  onQuickMessage: (message: string) => void;
  loading: boolean;
  chatId: string | null;
}

export function SessionPanel({
  panel,
  receivedAt,
  open,
  onClose,
  onEndChat,
  onQuickMessage,
  loading,
  chatId,
}: SessionPanelProps) {
  const isSheet = useMediaQuery("(max-width: 767px)");
  const asideRef = useRef<HTMLElement | null>(null);
  const titleId = useId();

  const remaining = useCountdown(
    panel.verified ? receivedAt : null,
    panel.verified ? panel.expires_in_seconds : null
  );
  const expired = remaining !== null && remaining <= 0;
  const verified = panel.verified && !expired;

  const [copiedId, setCopiedId] = useState<string | null>(null);
  const copyTimer = useRef<number | null>(null);

  const handleCopy = useCallback((value: string, key: string) => {
    if (!window.navigator.clipboard) return;
    void window.navigator.clipboard.writeText(value).catch(() => {});
    setCopiedId(key);
    if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
    copyTimer.current = window.setTimeout(() => setCopiedId(null), 2000);
  }, []);

  useEffect(
    () => () => {
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
    },
    []
  );

  // Escape closes; focus moves into the sheet/overlay and returns on close.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    const previous = document.activeElement as HTMLElement | null;
    asideRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (isSheet) previous?.focus();
    };
  }, [open, isSheet, onClose]);

  const references = panel.receipts
    .filter((receipt) => receipt.kind !== "handoff")
    .reverse();
  const handoff = [...panel.receipts]
    .reverse()
    .find((receipt) => receipt.kind === "handoff");

  const saveCopy = useCallback(() => {
    if (panel.receipts.length === 0) return;
    const now = new Date();
    const pad = (value: number) => String(value).padStart(2, "0");
    const dateSlug = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(
      now.getDate()
    )}`;
    const stamp = `${dateSlug} ${pad(now.getHours())}:${pad(now.getMinutes())}`;

    const lines = ["Rubies MFB references", `Saved ${stamp}`, ""];
    panel.receipts.forEach((receipt) => {
      lines.push(`${formatClock(receipt.at)} — ${receipt.summary}`);
      if (receipt.reference) lines.push(`Reference: ${receipt.reference}`);
      lines.push("");
    });

    const blob = new Blob([lines.join("\n")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `rubies-references-${dateSlug}.txt`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }, [panel.receipts]);

  return (
    <>
      <div
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-40 bg-black/35 transition-opacity duration-300 motion-reduce:transition-none xl:hidden",
          open ? "opacity-100" : "pointer-events-none opacity-0"
        )}
      />
      <aside
        ref={asideRef}
        aria-label="Session"
        aria-labelledby={isSheet ? titleId : undefined}
        role={isSheet ? "dialog" : undefined}
        aria-modal={isSheet ? true : undefined}
        tabIndex={-1}
        inert={!open}
        className={cn(
          "z-50 flex flex-col bg-[var(--surface)] outline-none transition-transform duration-300 ease-out motion-reduce:transition-none",
          // Phones: bottom sheet.
          "fixed inset-x-0 bottom-0 max-h-[85dvh] w-full rounded-t-2xl border-t border-[var(--border)]",
          open ? "translate-y-0" : "translate-y-full",
          // Tablets: right overlay.
          "md:inset-y-0 md:bottom-auto md:left-auto md:right-0 md:max-h-none md:w-80 md:rounded-none md:border-t-0 md:border-l",
          open ? "md:translate-x-0" : "md:translate-x-full",
          // Desktop: in-flow column.
          "xl:static xl:h-full xl:translate-x-0 xl:border-l xl:border-t-0",
          open ? "xl:w-80 xl:shrink-0" : "xl:w-0 xl:overflow-hidden xl:border-l-0"
        )}
      >
        <div className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-3">
          <div className="flex flex-col items-center gap-1.5 md:hidden">
            <span
              className="h-1 w-9 rounded-full bg-[var(--input-border)]"
              aria-hidden="true"
            />
          </div>
          <h2 id={titleId} className="flex-1 text-[14px] font-semibold">
            Session
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close session panel"
            className={ICON_BUTTON}
          >
            <X size={18} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <Section title="Session">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "inline-block size-2 rounded-full",
                  verified ? "bg-[var(--success)]" : "bg-[var(--muted)]"
                )}
                aria-hidden="true"
              />
              <span
                className={cn(
                  "text-[14px] font-medium",
                  verified ? "text-[var(--success)]" : "text-[var(--muted)]"
                )}
              >
                {verified ? "Verified" : "Not verified yet"}
              </span>
            </div>

            {verified && panel.phone_masked ? (
              <p className="mt-1.5 text-[13px] text-[var(--text)]">
                {panel.phone_masked}
              </p>
            ) : null}

            {verified && remaining !== null ? (
              <p
                className="mt-2 text-[13px] tabular-nums text-[var(--muted)]"
                aria-hidden="true"
              >
                Expires in {String(Math.floor(remaining / 60)).padStart(2, "0")}:
                {String(remaining % 60).padStart(2, "0")}
              </p>
            ) : null}

            {expired ? (
              <p className="mt-2 text-[13px] text-[var(--muted)]">
                Session expired. Verify again to continue.
              </p>
            ) : null}

            <button
              type="button"
              onClick={onEndChat}
              className={cn(OUTLINED_BUTTON, "mt-4 w-full")}
            >
              End chat and clear
            </button>
            <p className="mt-2 text-[12px] text-[var(--muted)]">
              Nothing from this chat is saved.
            </p>
          </Section>

          <Section title="Your references">
            {references.length === 0 ? (
              <p className="text-[13px] leading-snug text-[var(--muted)]">
                References from this chat, such as dispute numbers, will appear
                here.
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
                            label="reference"
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
              onClick={saveCopy}
              disabled={panel.receipts.length === 0}
              className={cn(OUTLINED_BUTTON, "mt-4 w-full")}
            >
              <Download size={15} aria-hidden="true" />
              Save a copy
            </button>
          </Section>

          {handoff ? (
            <Section title="Human handoff">
              <p className="text-[14px] font-medium text-[var(--text)]">
                A human agent has your ticket
              </p>
              {handoff.reference ? (
                <div className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-[var(--border)] px-2.5 py-1.5">
                  <span className="min-w-0 truncate font-mono text-[12.5px] text-[var(--text)]">
                    {handoff.reference}
                  </span>
                  <CopyButton
                    value={handoff.reference}
                    label="ticket reference"
                    copied={copiedId === handoff.id}
                    onCopy={(value) => handleCopy(value, handoff.id)}
                  />
                </div>
              ) : null}
              <div className="mt-3 rounded-lg bg-[var(--avatar-bg)] px-3 py-2.5">
                <p className="text-[12px] font-semibold uppercase tracking-[0.06em] text-[var(--muted)]">
                  What we shared with the agent
                </p>
                <p className="mt-1.5 text-[13px] leading-snug text-[var(--text)]">
                  {handoff.summary}
                </p>
              </div>
            </Section>
          ) : null}

          <Section title="Common tasks">
            <div className="flex flex-col gap-2">
              {COMMON_TASKS.map((task) => (
                <button
                  key={task.label}
                  type="button"
                  disabled={loading || !chatId}
                  onClick={() => {
                    onQuickMessage(task.message);
                    if (isSheet) onClose();
                  }}
                  className={cn(OUTLINED_BUTTON, "w-full justify-start text-left")}
                >
                  {task.label}
                </button>
              ))}
            </div>
          </Section>

          <Section title="Stay safe" className="border-b-0">
            <p className="text-[13px] leading-snug text-[var(--muted)]">
              This chat isn&rsquo;t saved. Ending it or closing the page clears
              everything.
            </p>
            <p className="mt-2 text-[13px] leading-snug text-[var(--muted)]">
              Rubies will never ask for your PIN, password or full card number.
            </p>
          </Section>
        </div>
      </aside>
    </>
  );
}
