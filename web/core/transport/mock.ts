import {
  emptyPanel,
  type PanelState,
  type StreamEvent,
} from "@/core/contract";
import {
  ChatExpiredError,
  ValidationError,
  type ChatTransport,
} from "@/core/transport/types";

interface MockAgentMessage {
  role: "agent";
  events: Array<Record<string, unknown>>;
  status: "streaming" | "done" | "error";
  at: string;
}

interface MockUserMessage {
  role: "user";
  text: string;
  at: string;
}

interface MockChat {
  history: Array<MockUserMessage | MockAgentMessage>;
  panel: PanelState;
  stage: "idle" | "awaiting-block";
}

const chats = new Map<string, MockChat>();
let counter = 0;

const now = () => new Date().toISOString();
const id = () => `${Date.now().toString(36)}-${(counter += 1)}`;

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true }
    );
  });
}

function receipt(kind: "card_block" | "handoff", summary: string, reference?: string) {
  return {
    id: id(),
    kind,
    reference: reference ?? null,
    summary,
    at: now(),
  };
}

function includes(text: string, words: RegExp): boolean {
  return words.test(text);
}

function chooseStage(chat: MockChat, text: string): string {
  if (chat.stage === "awaiting-block") {
    if (includes(text, /\b(yes|go ahead|confirm|ok)\b/i)) return "execute-block";
    if (includes(text, /\b(cancel|no|stop)\b/i)) return "cancel-block";
  }
  if (includes(text, /expire/i)) return "expired";
  if (includes(text, /human|agent|person/i)) return "handoff";
  if (includes(text, /fail|error|double debit|debited twice/i)) return "failing";
  if (includes(text, /card|lost|block/i)) return "lost-card";
  return "fee";
}

async function* sendMessage(
  chatId: string,
  text: string,
  signal?: AbortSignal
): AsyncIterable<StreamEvent> {
  const chat = chats.get(chatId);
  if (!chat) throw new ChatExpiredError();
  const trimmed = text.trim();
  if (!trimmed) throw new ValidationError("empty_message");
  if (trimmed.length > 2000) throw new ValidationError("message_too_long");
  if (chooseStage(chat, trimmed) === "expired") {
    chats.delete(chatId);
    throw new ChatExpiredError();
  }

  chat.history.push({ role: "user", text: trimmed, at: now() });
  const agent: MockAgentMessage = {
    role: "agent",
    events: [],
    status: "streaming",
    at: now(),
  };
  chat.history.push(agent);

  async function* emit(event: StreamEvent): AsyncGenerator<StreamEvent> {
    if (event.type !== "panel") {
      agent.events.push(
        event.type === "step"
          ? { type: "step", ...event.step }
          : event.type === "text"
            ? { type: "text", text: event.delta }
            : event.type === "done"
              ? { type: "done", citations: event.citations }
              : { type: "error", message: event.message }
      );
    }
    await wait(30, signal);
    yield event;
  }

  const stage = chooseStage(chat, trimmed);
  if (stage === "lost-card") {
    chat.stage = "awaiting-block";
    yield* emit({ type: "step", step: { id: "verify", status: "running", label: "Verifying you" } });
    yield* emit({ type: "step", step: { id: "verify", status: "done", label: "Verified you" } });
    yield* emit({ type: "step", step: { id: "block", status: "running", label: "Checking your card" } });
    yield* emit({ type: "step", step: { id: "block", status: "awaiting", label: "Waiting for your confirmation" } });
    yield* emit({ type: "text", delta: "Shall I block the card ending 0001?" });
    yield* emit({ type: "done", citations: [] });
  } else if (stage === "execute-block") {
    chat.stage = "idle";
    yield* emit({ type: "step", step: { id: "block", status: "running", label: "Blocking your card" } });
    yield* emit({ type: "step", step: { id: "block", status: "done", label: "Card blocked" } });
    yield* emit({ type: "text", delta: "Done — the card ending 0001 is blocked." });
    chat.panel = {
      ...chat.panel,
      verified: true,
      phone_masked: "+234 ••• ••• 4567",
      expires_in_seconds: 900,
      receipts: [
        ...chat.panel.receipts,
        receipt("card_block", "Card ending 0001 blocked."),
      ],
    };
    yield* emit({ type: "panel", panel: chat.panel });
    yield* emit({ type: "done", citations: [] });
  } else if (stage === "cancel-block") {
    chat.stage = "idle";
    yield* emit({ type: "step", step: { id: "block", status: "done", label: "No action taken" } });
    yield* emit({ type: "text", delta: "Okay, I haven’t blocked the card." });
    yield* emit({ type: "done", citations: [] });
  } else if (stage === "handoff") {
    chat.panel = {
      ...chat.panel,
      receipts: [
        ...chat.panel.receipts,
        receipt(
          "handoff",
          "Passed to a human agent: customer asked for a person.",
          "HT-123"
        ),
      ],
    };
    yield* emit({ type: "step", step: { id: "handoff", status: "running", label: "Passing you to a human agent" } });
    yield* emit({ type: "step", step: { id: "handoff", status: "done", label: "Ticket created" } });
    yield* emit({ type: "text", delta: "I’ve passed this to a human agent. Your ticket is HT-123." });
    yield* emit({ type: "panel", panel: chat.panel });
    yield* emit({ type: "done", citations: [] });
  } else if (stage === "failing") {
    yield* emit({ type: "step", step: { id: "lookup", status: "running", label: "Checking your transfer" } });
    yield* emit({ type: "step", step: { id: "lookup", status: "failed", label: "Couldn’t check your transfer" } });
    yield* emit({ type: "text", delta: "The transfer lookup failed. Please try again or ask for a human agent." });
    yield* emit({ type: "done", citations: [] });
  } else {
    yield* emit({ type: "step", step: { id: "fee", status: "running", label: "Checking the fee policy" } });
    yield* emit({ type: "step", step: { id: "fee", status: "done", label: "Checked the fee policy" } });
    yield* emit({ type: "text", delta: "Transfers above ₦50,000 cost ₦25." });
    yield* emit({ type: "text", delta: " This fee applies to each outward transfer." });
    yield* emit({
      type: "done",
      citations: [
        { document: "Fee Schedule", section: "Transfer fees" },
        { document: "Transfers", section: "Fees" },
      ],
    });
  }

  agent.status = "done";
  agent.at = now();
}

async function createChat(): Promise<string> {
  const chatId = `mock-${counter + 1}`;
  chats.set(chatId, { history: [], panel: emptyPanel(), stage: "idle" });
  return chatId;
}

async function deleteChat(chatId: string): Promise<void> {
  chats.delete(chatId);
}

async function loadHistory(chatId: string) {
  const chat = chats.get(chatId);
  if (!chat) throw new ChatExpiredError();
  return { messages: chat.history, panel: chat.panel };
}

async function getDevOtp(): Promise<string> {
  return "Demo OTP · 123456";
}

export const mockTransport: ChatTransport = {
  createChat,
  deleteChat,
  sendMessage,
  loadHistory,
  getDevOtp,
};
