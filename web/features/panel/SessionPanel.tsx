"use client";

import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { copy } from "@/core/config";
import type { PanelState } from "@/core/contract";
import { ICON_BUTTON } from "@/features/panel/panel-ui";
import { SessionSection } from "@/features/panel/SessionSection";
import { ReferencesSection } from "@/features/panel/ReferencesSection";
import { HandoffSection } from "@/features/panel/HandoffSection";
import { TasksSection } from "@/features/panel/TasksSection";
import { SafetySection } from "@/features/panel/SafetySection";
import { useCountdown } from "@/features/panel/use-countdown";
import { useSheet } from "@/features/panel/use-sheet";

export interface SessionPanelProps {
  panel: PanelState;
  receivedAt: number | null;
  open: boolean;
  onClose: () => void;
  onEndChat: () => void;
  onSend: (message: string) => void;
  loading: boolean;
  chatId: string | null;
}

export function SessionPanel({
  panel,
  receivedAt,
  open,
  onClose,
  onEndChat,
  onSend,
  loading,
  chatId,
}: SessionPanelProps) {
  const { isSheet, asideRef, titleId } = useSheet(open, onClose);
  const remaining = useCountdown(
    panel.verified ? receivedAt : null,
    panel.verified ? panel.expires_in_seconds : null
  );
  const expired = remaining !== null && remaining <= 0;
  const verified = panel.verified && !expired;
  const handoff = [...panel.receipts]
    .reverse()
    .find((receipt) => receipt.kind === "handoff");

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
        aria-label={copy.panel.aria}
        aria-labelledby={isSheet ? titleId : undefined}
        role={isSheet ? "dialog" : undefined}
        aria-modal={isSheet ? true : undefined}
        tabIndex={-1}
        inert={!open}
        className={cn(
          "z-50 flex flex-col bg-[var(--surface)] outline-none transition-transform duration-300 ease-out motion-reduce:transition-none",
          "fixed inset-x-0 bottom-0 max-h-[85dvh] w-full rounded-t-2xl border-t border-[var(--border)]",
          open ? "translate-y-0" : "translate-y-full",
          "md:inset-y-0 md:bottom-auto md:left-auto md:right-0 md:max-h-none md:w-80 md:rounded-none md:border-t-0 md:border-l",
          open ? "md:translate-x-0" : "md:translate-x-full",
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
            {copy.panel.title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={copy.panel.closeAria}
            className={ICON_BUTTON}
          >
            <X size={18} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <SessionSection
            panel={panel}
            remaining={remaining}
            expired={expired}
            verified={verified}
            onEndChat={onEndChat}
          />
          <ReferencesSection panel={panel} />
          {handoff ? <HandoffSection handoff={handoff} /> : null}
          <TasksSection
            loading={loading}
            chatId={chatId}
            isSheet={isSheet}
            onSend={onSend}
            onClose={onClose}
          />
          <SafetySection />
        </div>
      </aside>
    </>
  );
}
