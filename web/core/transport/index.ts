import { config } from "@/core/config";
import { httpTransport } from "@/core/transport/http";
import { mockTransport } from "@/core/transport/mock";
import type { ChatTransport } from "@/core/transport/types";

export const transport: ChatTransport =
  config.transport === "mock" ? mockTransport : httpTransport;
