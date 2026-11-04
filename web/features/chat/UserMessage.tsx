import { Message } from "@/components/ai-elements/message";
import { copy } from "@/core/config";

export function UserMessage({ text }: { text: string }) {
  return (
    <Message from="user" aria-label={copy.chat.userAria}>
      <div className="w-fit max-w-[70%] self-end whitespace-pre-wrap break-words rounded-tl-[18px] rounded-tr-[18px] rounded-bl-[18px] rounded-br-[4px] bg-[var(--accent)] px-4 py-2.5 text-[15px] leading-[1.5] text-white">
        {text}
      </div>
    </Message>
  );
}
