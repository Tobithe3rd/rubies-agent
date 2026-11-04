import { useCallback, useEffect, useRef, useState } from "react";
import { copy } from "@/core/config";
import type { Receipt } from "@/core/contract";

export function formatClock(at: string): string {
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-NG", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function buildReceiptsText(receipts: Receipt[]): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  const dateSlug = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(
    now.getDate()
  )}`;
  const stamp = `${dateSlug} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
  const lines = [copy.panel.referencesFileTitle, `${copy.panel.savedPrefix}${stamp}`, ""];
  receipts.forEach((receipt) => {
    lines.push(`${formatClock(receipt.at)} — ${receipt.summary}`);
    if (receipt.reference) {
      lines.push(`${copy.panel.referencePrefix}${receipt.reference}`);
    }
    lines.push("");
  });
  return lines.join("\n");
}

export function saveCopy(receipts: Receipt[]): void {
  if (receipts.length === 0) return;
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  const dateSlug = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(
    now.getDate()
  )}`;
  const blob = new Blob([buildReceiptsText(receipts)], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${copy.panel.referencesFileName}-${dateSlug}.txt`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function useCopy() {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const handleCopy = useCallback((value: string, key: string) => {
    if (!window.navigator.clipboard) return;
    void window.navigator.clipboard.writeText(value).catch(() => {});
    setCopiedId(key);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopiedId(null), 2000);
  }, []);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    []
  );

  return { copiedId, handleCopy };
}
