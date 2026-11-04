/** The single source of truth for every payload shared with adapters/web. */

export type StepStatus = "running" | "done" | "failed" | "awaiting";

export interface Step {
  id: string;
  status: StepStatus;
  label: string;
}

export interface Citation {
  document: string;
  section: string;
}

export type ReceiptKind = "dispute" | "card_block" | "handoff";

export interface Receipt {
  id: string;
  kind: ReceiptKind;
  reference: string | null;
  summary: string;
  at: string;
}

export interface PanelState {
  verified: boolean;
  phone_masked: string | null;
  expires_in_seconds: number | null;
  receipts: Receipt[];
}

export type MessageStatus = "streaming" | "done" | "stopped" | "error";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  steps: Step[];
  citations: Citation[];
  status: MessageStatus;
  canRetry?: boolean;
  /** Internal: the next text chunk starts a new paragraph after a step. */
  stepBreak?: boolean;
}

export type StreamEvent =
  | { type: "step"; step: Step }
  | { type: "text"; delta: string }
  | { type: "done"; citations: Citation[] }
  | { type: "panel"; panel: PanelState }
  | { type: "error"; message: string };

export interface HistoryPayload {
  messages: unknown[];
  panel: PanelState;
}

const STEP_STATUSES: StepStatus[] = ["running", "done", "failed", "awaiting"];
const RECEIPT_KINDS: ReceiptKind[] = ["dispute", "card_block", "handoff"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object";
}

export function isStep(value: unknown): value is Step {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.label === "string" &&
    STEP_STATUSES.includes(value.status as StepStatus)
  );
}

export function isCitation(value: unknown): value is Citation {
  if (!isRecord(value)) return false;
  return (
    typeof value.document === "string" && typeof value.section === "string"
  );
}

export function parseReceipt(value: unknown): Receipt | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.id !== "string" ||
    !RECEIPT_KINDS.includes(value.kind as ReceiptKind) ||
    (value.reference !== null && typeof value.reference !== "string") ||
    typeof value.summary !== "string" ||
    typeof value.at !== "string"
  ) {
    return null;
  }
  return {
    id: value.id,
    kind: value.kind as ReceiptKind,
    reference: value.reference,
    summary: value.summary,
    at: value.at,
  };
}

export function parsePanel(value: unknown): PanelState | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.verified !== "boolean" ||
    (value.phone_masked !== null && typeof value.phone_masked !== "string") ||
    (value.expires_in_seconds !== null &&
      (typeof value.expires_in_seconds !== "number" ||
        !Number.isFinite(value.expires_in_seconds))) ||
    !Array.isArray(value.receipts)
  ) {
    return null;
  }
  return {
    verified: value.verified,
    phone_masked: value.phone_masked,
    expires_in_seconds: value.expires_in_seconds,
    receipts: value.receipts
      .map(parseReceipt)
      .filter((receipt): receipt is Receipt => receipt !== null),
  };
}

export function emptyPanel(): PanelState {
  return {
    verified: false,
    phone_masked: null,
    expires_in_seconds: null,
    receipts: [],
  };
}

export function parseStreamEvent(
  event: string,
  payload: unknown
): StreamEvent | null {
  if (!isRecord(payload)) return null;

  if (event === "step") {
    return isStep(payload) ? { type: "step", step: payload } : null;
  }
  if (event === "text") {
    return typeof payload.delta === "string" && payload.delta
      ? { type: "text", delta: payload.delta }
      : null;
  }
  if (event === "done") {
    const citations = Array.isArray(payload.citations)
      ? payload.citations.filter(isCitation)
      : [];
    return { type: "done", citations };
  }
  if (event === "panel") {
    const panel = parsePanel(payload);
    return panel ? { type: "panel", panel } : null;
  }
  if (event === "error") {
    const message =
      typeof payload.message === "string" && payload.message
        ? payload.message
        : "Something went wrong.";
    return { type: "error", message };
  }
  return null;
}

export function parseHistoryPayload(value: unknown): HistoryPayload | null {
  if (!isRecord(value) || !Array.isArray(value.messages)) return null;
  const panel = parsePanel(value.panel);
  if (!panel) return null;
  return { messages: value.messages, panel };
}
