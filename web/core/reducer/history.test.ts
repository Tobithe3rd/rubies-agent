import { describe, expect, it } from "vitest";
import { mapHistoryMessages } from "@/core/reducer/history";

const history = [
  { role: "user", text: "My card is missing", at: "2026-01-01T10:00:00+01:00" },
  {
    role: "agent",
    status: "done",
    at: "2026-01-01T10:00:05+01:00",
    events: [
      { type: "step", id: "step-a", status: "done", label: "Verified you" },
      { type: "text", text: "I can help with that." },
      { type: "step", id: "step-b", status: "awaiting", label: "Waiting for you" },
      { type: "text", text: "Shall I block the card?" },
      {
        type: "done",
        citations: [{ document: "Card Policy", section: "2. Blocking a card" }],
      },
    ],
  },
];

describe("mapHistoryMessages", () => {
  it("maps user and agent roles", () => {
    const messages = mapHistoryMessages(history);
    expect(messages).toHaveLength(2);
    expect(messages[0].role).toBe("user");
    expect(messages[0].text).toBe("My card is missing");
    expect(messages[1].role).toBe("assistant");
  });

  it("keeps step ids, statuses and labels in order", () => {
    const [, agent] = mapHistoryMessages(history);
    expect(agent.steps.map((step) => [step.id, step.status, step.label])).toEqual([
      ["step-a", "done", "Verified you"],
      ["step-b", "awaiting", "Waiting for you"],
    ]);
    expect(agent.steps.at(-1)?.status).toBe("awaiting");
  });

  it("joins text across steps with the live paragraph break", () => {
    const [, agent] = mapHistoryMessages(history);
    expect(agent.text).toBe("I can help with that.\n\nShall I block the card?");
  });

  it("maps citations into source pills data", () => {
    const [, agent] = mapHistoryMessages(history);
    expect(agent.citations).toEqual([
      { document: "Card Policy", section: "2. Blocking a card" },
    ]);
  });

  it("maps done status", () => {
    const [, agent] = mapHistoryMessages(history);
    expect(agent.status).toBe("done");
    expect(agent.canRetry).toBe(false);
  });

  it("maps streaming status and keeps it streaming", () => {
    const [agent] = mapHistoryMessages([
      {
        role: "agent",
        status: "streaming",
        events: [
          { type: "step", id: "step-live", status: "running", label: "Checking" },
          { type: "text", text: "Working" },
        ],
      },
    ]);
    expect(agent.status).toBe("streaming");
    expect(agent.steps[0].id).toBe("step-live");
  });

  it("maps error status and falls back to the error message", () => {
    const [agent] = mapHistoryMessages([
      {
        role: "agent",
        status: "error",
        events: [{ type: "error", message: "Something went wrong." }],
      },
    ]);
    expect(agent.status).toBe("error");
    expect(agent.text).toBe("Something went wrong.");
    expect(agent.canRetry).toBe(true);
  });

  it("maps stopped status", () => {
    const [agent] = mapHistoryMessages([
      {
        role: "agent",
        status: "stopped",
        events: [{ type: "text", text: "Partial reply" }],
      },
    ]);
    expect(agent.status).toBe("stopped");
    expect(agent.canRetry).toBe(true);
  });

  it("ignores malformed history items", () => {
    expect(mapHistoryMessages(null)).toEqual([]);
    expect(mapHistoryMessages([{ role: "system", text: "x" }])).toEqual([]);
    expect(
      mapHistoryMessages([
        { role: "agent", status: "done", events: [{ type: "step", id: 1 }] },
      ])[0].steps
    ).toHaveLength(0);
  });
});
