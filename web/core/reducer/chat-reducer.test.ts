import { describe, expect, it } from "vitest";
import { chatReducer, initialState } from "@/core/reducer/chat-reducer";
import { mapHistoryMessages } from "@/core/reducer/history";
import type { ChatState } from "@/core/reducer/chat-reducer";

const sent = () =>
  chatReducer(initialState, {
    type: "sent",
    assistantId: "assistant-1",
    user: { id: "user-1", text: "hello" },
  });

const step = (id: string, status: "running" | "done" | "awaiting", label: string) =>
  ({ type: "step" as const, step: { id, status, label } });

describe("chatReducer", () => {
  it("updates a step by id instead of appending it twice", () => {
    let state = sent();
    state = chatReducer(state, {
      type: "stream-event",
      id: "assistant-1",
      event: step("step-1", "running", "Checking"),
      at: 1,
    });
    state = chatReducer(state, {
      type: "stream-event",
      id: "assistant-1",
      event: step("step-1", "done", "Checked"),
      at: 2,
    });
    const message = state.messages[1];
    expect(message.steps).toHaveLength(1);
    expect(message.steps[0]).toMatchObject({ id: "step-1", status: "done" });
  });

  it("joins text after a step with a paragraph break", () => {
    let state = sent();
    state = chatReducer(state, {
      type: "stream-event",
      id: "assistant-1",
      event: step("step-1", "done", "Checked"),
      at: 1,
    });
    state = chatReducer(state, {
      type: "stream-event",
      id: "assistant-1",
      event: { type: "text", delta: "first" },
      at: 2,
    });
    state = chatReducer(state, {
      type: "stream-event",
      id: "assistant-1",
      event: step("step-2", "done", "Checked again"),
      at: 3,
    });
    state = chatReducer(state, {
      type: "stream-event",
      id: "assistant-1",
      event: { type: "text", delta: "second" },
      at: 4,
    });
    state = chatReducer(state, {
      type: "stream-event",
      id: "assistant-1",
      event: { type: "text", delta: " more" },
      at: 5,
    });
    expect(state.messages[1].text).toBe("first\n\nsecond more");
  });

  it("keeps the awaiting step so quick replies can show after done", () => {
    let state = sent();
    state = chatReducer(state, {
      type: "stream-event",
      id: "assistant-1",
      event: step("step-1", "awaiting", "Waiting for you"),
      at: 1,
    });
    state = chatReducer(state, {
      type: "stream-event",
      id: "assistant-1",
      event: { type: "text", delta: "Shall I go ahead?" },
      at: 2,
    });
    state = chatReducer(state, {
      type: "stream-event",
      id: "assistant-1",
      event: { type: "done", citations: [] },
      at: 3,
    });
    const message = state.messages[1];
    expect(message.status).toBe("done");
    expect(message.steps.at(-1)?.status).toBe("awaiting");
  });

  it("marks a stopped reply retryable", () => {
    let state = sent();
    state = chatReducer(state, { type: "stopped", id: "assistant-1" });
    expect(state.messages[1]).toMatchObject({
      status: "stopped",
      canRetry: true,
    });
  });

  it("marks an interrupted reply as an error", () => {
    let state = sent();
    state = chatReducer(state, { type: "interrupted", id: "assistant-1" });
    expect(state.messages[1]).toMatchObject({
      status: "error",
      canRetry: true,
    });
  });

  it("restores done, streaming and error history states", () => {
    const cases = [
      { status: "done", events: [{ type: "text", text: "Done" }] },
      { status: "streaming", events: [{ type: "text", text: "Working" }] },
      { status: "error", events: [{ type: "error", message: "Failed" }] },
    ] as const;
    cases.forEach((item) => {
      const messages = mapHistoryMessages([
        { role: "agent", status: item.status, events: [...item.events] },
      ]);
      const state = chatReducer(initialState, {
        type: "history-restored",
        messages,
        panel: {
          verified: true,
          phone_masked: "+234 ••• ••• 4567",
          expires_in_seconds: 600,
          receipts: [],
        },
        at: 42,
      });
      expect(state.messages[0].status).toBe(
        item.status === "error" ? "error" : item.status
      );
      expect(state.panel.verified).toBe(true);
      expect(state.panelReceivedAt).toBe(42);
    });
  });

  it("updates the panel and its receipt time", () => {
    const state = chatReducer(initialState, {
      type: "stream-event",
      id: "assistant-1",
      event: {
        type: "panel",
        panel: {
          verified: true,
          phone_masked: null,
          expires_in_seconds: 60,
          receipts: [],
        },
      },
      at: 99,
    });
    expect(state.panel.expires_in_seconds).toBe(60);
    expect(state.panelReceivedAt).toBe(99);
  });

  it("resets and clears an expired chat", () => {
    const filled: ChatState = {
      ...sent(),
      panel: {
        verified: true,
        phone_masked: null,
        expires_in_seconds: 60,
        receipts: [],
      },
      panelReceivedAt: 10,
    };
    for (const type of ["reset", "chat-expired"] as const) {
      const state = chatReducer(filled, { type });
      expect(state.messages).toEqual([]);
      expect(state.panel.receipts).toEqual([]);
      expect(state.panelReceivedAt).toBeNull();
    }
  });
});
