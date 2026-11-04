"use client";

import { Loader } from "@/components/ai-elements/loader";
import {
  Conversation,
  ConversationContent,
} from "@/components/ai-elements/conversation";
import { useAutoscroll } from "@/features/chat/use-autoscroll";
import { EmptyState } from "@/features/chat/EmptyState";
import { UserMessage } from "@/features/chat/UserMessage";
import { AgentMessage } from "@/features/chat/AgentMessage";
import { copy, quickReplies } from "@/core/config";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/core/contract";

interface MessageListProps {
  messages: ChatMessage[];
  restoring: boolean;
  loading: boolean;
  chatId: string | null;
  onSend: (message: string) => void;
  onQuickMessage: (message: string) => void;
  onRetry: () => void;
}

export function MessageList({
  messages,
  restoring,
  loading,
  chatId,
  onSend,
  onQuickMessage,
  onRetry,
}: MessageListProps) {
  const conversationRef = useAutoscroll(restoring);
  const lastMessage = messages[messages.length - 1];
  const lastStep = lastMessage?.steps[lastMessage.steps.length - 1];
  const showQuickReplies =
    !restoring &&
    lastMessage?.role === "assistant" &&
    lastMessage.status !== "streaming" &&
    lastStep?.status === "awaiting";

  return (
    <Conversation
      className="min-h-0 flex-1"
      contextRef={conversationRef}
      initial="instant"
    >
      <ConversationContent
        className={cn(
          "mx-auto w-full max-w-3xl gap-5 px-4 py-6 pb-8 sm:px-6",
          messages.length === 0 && "min-h-full justify-center"
        )}
      >
        {messages.length === 0 && restoring && (
          <div
            role="status"
            className="flex flex-col items-center justify-center px-2 py-12 text-center"
          >
            <Loader size={18} />
            <p className="mt-3 text-[14px] text-[var(--muted)]">
              {copy.chat.restoring}
            </p>
          </div>
        )}

        {messages.length === 0 && !restoring && (
          <EmptyState
            disabled={loading || restoring || !chatId}
            onSend={onSend}
          />
        )}

        {messages.map((message) =>
          message.role === "user" ? (
            <UserMessage key={message.id} text={message.text} />
          ) : (
            <AgentMessage
              key={message.id}
              message={message}
              showQuickReplies={
                message.id === lastMessage?.id && Boolean(showQuickReplies)
              }
              replies={quickReplies}
              loading={loading}
              restoring={restoring}
              chatId={chatId}
              onQuickMessage={onQuickMessage}
              onRetry={onRetry}
            />
          )
        )}
      </ConversationContent>
    </Conversation>
  );
}
