import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  parseHistoryPayload,
  parseReceipt,
  parseStreamEvent,
} from "@/core/contract";

const root = new URL("../../contract/", import.meta.url);
const eventsContract = JSON.parse(
  readFileSync(new URL("events.json", root), "utf8")
);
const fixtureDir = fileURLToPath(new URL("fixtures/", root));
const fixtureFiles = readdirSync(fixtureDir).filter((name) =>
  name.endsWith("-stream.json")
);

function requiredKeys(event: string): string[] {
  return eventsContract.events[event]?.required ?? [];
}

describe("stream fixtures match the contract", () => {
  it("has a contract entry for every fixture event name", () => {
    expect(Object.keys(eventsContract.events).sort()).toEqual([
      "done",
      "error",
      "panel",
      "step",
      "text",
    ]);
    expect(fixtureFiles.length).toBeGreaterThan(0);
  });

  fixtureFiles.forEach((file) => {
    it(`parses ${file} with the runtime guards`, () => {
      const fixture = JSON.parse(
        readFileSync(new URL(`fixtures/${file}`, root), "utf8")
      );
      expect(fixture.events.length).toBeGreaterThan(0);
      fixture.events.forEach(
        (item: { event: string; data: Record<string, unknown> }) => {
          const keys = requiredKeys(item.event);
          expect(keys.length).toBeGreaterThan(0);
          keys.forEach((key) => expect(item.data).toHaveProperty(key));
          expect(parseStreamEvent(item.event, item.data)).not.toBeNull();
          if (item.event === "panel") {
            const receipts = item.data.receipts as unknown[];
            receipts.forEach((receipt) => {
              expect(parseReceipt(receipt)).not.toBeNull();
              const receiptContract = eventsContract.receipt;
              receiptContract.required.forEach((key: string) =>
                expect(receipt).toHaveProperty(key)
              );
            });
          }
        }
      );
    });
  });
});

describe("history fixture matches the contract", () => {
  it("parses the payload and the recorded messages", () => {
    const fixture = JSON.parse(
      readFileSync(new URL("fixtures/history.json", root), "utf8")
    );
    const payload = parseHistoryPayload(fixture);
    expect(payload).not.toBeNull();
    eventsContract.history.required.forEach((key: string) =>
      expect(fixture).toHaveProperty(key)
    );
    fixture.messages.forEach((message: Record<string, unknown>) => {
      const shape = eventsContract.history.message[message.role as string];
      shape.required.forEach((key: string) =>
        expect(message).toHaveProperty(key)
      );
      if (message.role === "agent") {
        (message.events as Array<Record<string, unknown>>).forEach((event) => {
          const eventShape =
            eventsContract.history.agent_event[event.type as string];
          eventShape.required.forEach((key: string) =>
            expect(event).toHaveProperty(key)
          );
        });
      }
    });
    payload?.panel.receipts.forEach((receipt) => {
      eventsContract.receipt.required.forEach((key: string) =>
        expect(receipt).toHaveProperty(key)
      );
    });
  });
});
