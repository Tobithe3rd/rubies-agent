import { ChatExpiredError } from "@/lib/api";
import { config } from "@/lib/config";

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

export interface SessionReceipt {
  id: string;
  kind: ReceiptKind;
  reference: string | null;
  summary: string;
  at: string;
}

export interface SessionPanel {
  verified: boolean;
  phone_masked: string | null;
  expires_in_seconds: number | null;
  receipts: SessionReceipt[];
}

export function emptyPanel(): SessionPanel {
  return {
    verified: false,
    phone_masked: null,
    expires_in_seconds: null,
    receipts: [],
  };
}

export interface StreamHandlers {
  onStep?: (step: Step) => void;
  onText?: (delta: string) => void;
  onPanel?: (panel: SessionPanel) => void;
  onDone?: (citations: Citation[]) => void;
  onError?: (message: string) => void;
}

function parseReceipt(value: unknown): SessionReceipt | null {
  if (!value || typeof value !== "object") return null;
  const receipt = value as Record<string, unknown>;
  if (
    typeof receipt.id !== "string" ||
    (receipt.kind !== "dispute" &&
      receipt.kind !== "card_block" &&
      receipt.kind !== "handoff") ||
    (receipt.reference !== null && typeof receipt.reference !== "string") ||
    typeof receipt.summary !== "string" ||
    typeof receipt.at !== "string"
  ) {
    return null;
  }
  return {
    id: receipt.id,
    kind: receipt.kind,
    reference: receipt.reference,
    summary: receipt.summary,
    at: receipt.at,
  };
}

export function parsePanel(value: unknown): SessionPanel | null {
  if (!value || typeof value !== "object") return null;
  const panel = value as Record<string, unknown>;
  if (
    typeof panel.verified !== "boolean" ||
    (panel.phone_masked !== null && typeof panel.phone_masked !== "string") ||
    (panel.expires_in_seconds !== null &&
      (typeof panel.expires_in_seconds !== "number" ||
        !Number.isFinite(panel.expires_in_seconds))) ||
    !Array.isArray(panel.receipts)
  ) {
    return null;
  }

  return {
    verified: panel.verified,
    phone_masked: panel.phone_masked,
    expires_in_seconds: panel.expires_in_seconds,
    receipts: panel.receipts
      .map(parseReceipt)
      .filter((receipt): receipt is SessionReceipt => receipt !== null),
  };
}

export class StreamHttpError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail || "Message failed");
    this.name = "StreamHttpError";
    this.status = status;
    this.detail = detail;
  }
}

interface ParsedEvent {
  event: string;
  data: string;
}

function parseEvent(raw: string): ParsedEvent | null {
  let event = "message";
  const data: string[] = [];

  for (const line of raw.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }

  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

/**
 * POST a message and consume the adapter's SSE stream.
 * HTTP failures (chat_expired, 400) are thrown before reading the body.
 */
export async function streamMessage(
  chatId: string,
  message: string,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${config.apiUrl}/chats/${chatId}/messages/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ message }),
    signal,
  });

  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string };
    if (res.status === 404 && body.detail === "chat_expired") {
      throw new ChatExpiredError();
    }
    throw new StreamHttpError(res.status, body.detail || "Message failed");
  }

  if (!res.body) throw new Error("Stream unavailable");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  const dispatch = (parsed: ParsedEvent) => {
    let payload: unknown;
    try {
      payload = JSON.parse(parsed.data);
    } catch {
      return;
    }
    if (!payload || typeof payload !== "object") return;

    if (parsed.event === "step") {
      const step = payload as Partial<Step>;
      if (
        typeof step.id === "string" &&
        typeof step.label === "string" &&
        (step.status === "running" ||
          step.status === "done" ||
          step.status === "failed" ||
          step.status === "awaiting")
      ) {
        handlers.onStep?.({
          id: step.id,
          status: step.status,
          label: step.label,
        });
      }
    } else if (parsed.event === "text") {
      const delta = (payload as { delta?: unknown }).delta;
      if (typeof delta === "string" && delta) handlers.onText?.(delta);
    } else if (parsed.event === "panel") {
      const panel = parsePanel(payload);
      if (panel) handlers.onPanel?.(panel);
    } else if (parsed.event === "done") {
      const citations = (payload as { citations?: unknown }).citations;
      handlers.onDone?.(Array.isArray(citations) ? (citations as Citation[]) : []);
      finished = true;
    } else if (parsed.event === "error") {
      const detail = (payload as { message?: unknown }).message;
      handlers.onError?.(
        typeof detail === "string" && detail ? detail : "Something went wrong."
      );
      finished = true;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseEvent(raw);
      if (parsed) dispatch(parsed);
      boundary = buffer.indexOf("\n\n");
    }
  }

  buffer += decoder.decode();
  const rest = parseEvent(buffer.replace(/\r\n/g, "\n"));
  if (rest) dispatch(rest);

  if (!finished) throw new Error("Stream interrupted");
}
