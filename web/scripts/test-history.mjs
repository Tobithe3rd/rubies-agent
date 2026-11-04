import assert from "node:assert/strict";
import { mapHistoryMessages } from "../lib/history.ts";

let passed = 0;

function check(name, fn) {
  fn();
  passed += 1;
  console.log(`PASS: ${name}`);
}

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

check("maps user and agent roles", () => {
  const messages = mapHistoryMessages(history);
  assert.equal(messages.length, 2);
  assert.equal(messages[0].role, "user");
  assert.equal(messages[0].text, "My card is missing");
  assert.equal(messages[1].role, "assistant");
});

check("keeps step ids, statuses and labels in order", () => {
  const [, agent] = mapHistoryMessages(history);
  assert.deepEqual(
    agent.steps.map((step) => [step.id, step.status, step.label]),
    [
      ["step-a", "done", "Verified you"],
      ["step-b", "awaiting", "Waiting for you"],
    ]
  );
  assert.equal(agent.steps.at(-1).status, "awaiting");
});

check("joins text across steps with the live paragraph break", () => {
  const [, agent] = mapHistoryMessages(history);
  assert.equal(agent.text, "I can help with that.\n\nShall I block the card?");
});

check("maps citations into source pills data", () => {
  const [, agent] = mapHistoryMessages(history);
  assert.deepEqual(agent.citations, [
    { document: "Card Policy", section: "2. Blocking a card" },
  ]);
});

check("maps done status", () => {
  const [, agent] = mapHistoryMessages(history);
  assert.equal(agent.status, "done");
  assert.equal(agent.canRetry, false);
});

check("maps streaming status and keeps it streaming", () => {
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
  assert.equal(agent.status, "streaming");
  assert.equal(agent.steps[0].id, "step-live");
});

check("maps error status and falls back to the error message", () => {
  const [agent] = mapHistoryMessages([
    {
      role: "agent",
      status: "error",
      events: [{ type: "error", message: "Something went wrong." }],
    },
  ]);
  assert.equal(agent.status, "error");
  assert.equal(agent.text, "Something went wrong.");
  assert.equal(agent.canRetry, true);
});

check("maps stopped status", () => {
  const [agent] = mapHistoryMessages([
    {
      role: "agent",
      status: "stopped",
      events: [{ type: "text", text: "Partial reply" }],
    },
  ]);
  assert.equal(agent.status, "stopped");
  assert.equal(agent.canRetry, true);
});

check("ignores malformed history items", () => {
  assert.deepEqual(mapHistoryMessages(null), []);
  assert.deepEqual(mapHistoryMessages([{ role: "system", text: "x" }]), []);
  assert.equal(
    mapHistoryMessages([
      { role: "agent", status: "done", events: [{ type: "step", id: 1 }] },
    ])[0].steps.length,
    0
  );
});

console.log(`RESULT: ${passed} passed, 0 failed`);
