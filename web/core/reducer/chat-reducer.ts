import {
  emptyPanel,
  type ChatMessage,
  type PanelState,
  type StreamEvent,
} from "@/core/contract";

export interface ChatStatus {
  loading: boolean;
  restoring: boolean;
  restoreFailed: boolean;
}

export interface ChatNotices {
  notice: string | null;
  incomplete: boolean;
  error: string | null;
}

export interface ChatState {
  messages: ChatMessage[];
  panel: PanelState;
  panelReceivedAt: number | null;
  status: ChatStatus;
  notices: ChatNotices;
}

export type ChatAction =
  | {
      type: "sent";
      assistantId: string;
      user: { id: string; text: string } | null;
    }
  | { type: "stream-event"; id: string; event: StreamEvent; at: number }
  | { type: "stream-ended"; id: string }
  | { type: "stopped"; id: string }
  | { type: "interrupted"; id: string }
  | {
      type: "history-restored";
      messages: ChatMessage[];
      panel: PanelState;
      at: number;
    }
  | { type: "reset" }
  | { type: "chat-expired" }
  | { type: "message-removed"; id: string }
  | { type: "notice"; message: string | null }
  | { type: "error"; message: string | null }
  | { type: "loading"; value: boolean }
  | { type: "restoring"; value: boolean }
  | { type: "restore-failed"; value: boolean }
  | { type: "incomplete"; value: boolean };

export const initialState: ChatState = {
  messages: [],
  panel: emptyPanel(),
  panelReceivedAt: null,
  status: { loading: false, restoring: false, restoreFailed: false },
  notices: { notice: null, incomplete: false, error: null },
};

function patch(
  messages: ChatMessage[],
  id: string,
  change: (message: ChatMessage) => ChatMessage
): ChatMessage[] {
  return messages.map((message) => (message.id === id ? change(message) : message));
}

function applyEvent(
  state: ChatState,
  id: string,
  event: StreamEvent,
  at: number
): ChatState {
  if (event.type === "panel") {
    return { ...state, panel: event.panel, panelReceivedAt: at };
  }

  const messages = patch(state.messages, id, (message) => {
    if (event.type === "step") {
      const exists = message.steps.some((step) => step.id === event.step.id);
      return {
        ...message,
        steps: exists
          ? message.steps.map((step) => (step.id === event.step.id ? event.step : step))
          : [...message.steps, event.step],
        stepBreak: true,
      };
    }
    if (event.type === "text") {
      const separator = message.stepBreak && message.text ? "\n\n" : "";
      return {
        ...message,
        text: message.text + separator + event.delta,
        stepBreak: false,
      };
    }
    if (event.type === "done") {
      return {
        ...message,
        citations: event.citations,
        status: "done",
      };
    }
    return {
      ...message,
      text: message.text || event.message,
      status: "error",
      canRetry: true,
    };
  });

  return { ...state, messages };
}

function resetState(state: ChatState): ChatState {
  return {
    ...initialState,
    status: { ...state.status, restoreFailed: false },
  };
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "sent": {
      const user: ChatMessage[] = action.user
        ? [
            {
              id: action.user.id,
              role: "user",
              text: action.user.text,
              steps: [],
              citations: [],
              status: "done",
            },
          ]
        : [];
      return {
        ...state,
        messages: [
          ...state.messages,
          ...user,
          {
            id: action.assistantId,
            role: "assistant",
            text: "",
            steps: [],
            citations: [],
            status: "streaming",
          },
        ],
      };
    }
    case "stream-event":
      return applyEvent(state, action.id, action.event, action.at);
    case "stream-ended":
      return {
        ...state,
        messages: patch(state.messages, action.id, (message) =>
          message.status === "streaming" ? { ...message, status: "done" } : message
        ),
      };
    case "stopped":
      return {
        ...state,
        messages: patch(state.messages, action.id, (message) =>
          message.status === "streaming"
            ? { ...message, status: "stopped", canRetry: true }
            : message
        ),
      };
    case "interrupted":
      return {
        ...state,
        messages: patch(state.messages, action.id, (message) => ({
          ...message,
          status: "error",
          canRetry: true,
        })),
      };
    case "history-restored":
      return {
        ...state,
        messages: action.messages,
        panel: action.panel,
        panelReceivedAt: action.at,
      };
    case "reset":
    case "chat-expired":
      return resetState(state);
    case "message-removed":
      return {
        ...state,
        messages: state.messages.filter((message) => message.id !== action.id),
      };
    case "notice":
      return { ...state, notices: { ...state.notices, notice: action.message } };
    case "error":
      return { ...state, notices: { ...state.notices, error: action.message } };
    case "loading":
      return { ...state, status: { ...state.status, loading: action.value } };
    case "restoring":
      return { ...state, status: { ...state.status, restoring: action.value } };
    case "restore-failed":
      return {
        ...state,
        status: { ...state.status, restoreFailed: action.value },
      };
    case "incomplete":
      return {
        ...state,
        notices: { ...state.notices, incomplete: action.value },
      };
    default:
      return state;
  }
}
