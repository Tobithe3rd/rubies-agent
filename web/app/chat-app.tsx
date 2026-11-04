"use client";

import {
  useCallback,
  useState,
  useSyncExternalStore,
} from "react";
import { config } from "@/core/config";
import { transport } from "@/core/transport";
import { ChatExpiredError } from "@/core/transport/types";
import { ChatScreen } from "@/features/chat/ChatScreen";
import { useChat } from "@/features/chat/use-chat";
import { SessionPanel } from "@/features/panel/SessionPanel";
import { useCountdown } from "@/features/panel/use-countdown";

function subscribeDesktopViewport(onChange: () => void) {
  const media = window.matchMedia("(min-width: 1280px)");
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

export function ChatApp() {
  const chat = useChat();
  const [showOtp, setShowOtp] = useState(false);
  const [otpLine, setOtpLine] = useState("");
  const remaining = useCountdown(
    chat.panel.verified ? chat.panelReceivedAt : null,
    chat.panel.verified ? chat.panel.expires_in_seconds : null
  );
  const verificationExpired = remaining !== null && remaining <= 0;

  // Desktop opens the panel by default; the user's toggle overrides it.
  const derivedDefault = useSyncExternalStore(
    subscribeDesktopViewport,
    () => window.matchMedia("(min-width: 1280px)").matches,
    () => false
  );
  const [panelOverride, setPanelOverride] = useState<boolean | null>(null);
  const panelOpen = panelOverride ?? derivedDefault;
  const togglePanel = useCallback(
    () => setPanelOverride((value) => !(value ?? derivedDefault)),
    [derivedDefault]
  );

  const handleNewChat = useCallback(() => {
    setShowOtp(false);
    setOtpLine("");
    void chat.newChat();
  }, [chat]);

  const handleOtp = useCallback(async () => {
    if (!chat.chatId) return;
    if (showOtp) {
      setShowOtp(false);
      return;
    }
    try {
      const line = await transport.getDevOtp(chat.chatId);
      setOtpLine(line);
      setShowOtp(true);
    } catch (error) {
      setShowOtp(false);
      setOtpLine("");
      if (error instanceof ChatExpiredError) {
        await chat.recoverExpiredChat();
      }
    }
  }, [chat, showOtp]);

  return (
    <main className="flex h-dvh bg-[var(--ground)] font-sans text-[var(--text)]">
      <ChatScreen
        chat={chat}
        panelOpen={panelOpen}
        panelEnabled={config.panelEnabled}
        verificationExpired={verificationExpired}
        showOtp={showOtp}
        otpLine={otpLine}
        onTogglePanel={togglePanel}
        onToggleOtp={handleOtp}
        onNewChat={handleNewChat}
      />
      {config.panelEnabled && (
        <SessionPanel
          panel={chat.panel}
          receivedAt={chat.panelReceivedAt}
          open={panelOpen}
          onClose={() => setPanelOverride(false)}
          onEndChat={handleNewChat}
          onSend={chat.submit}
          loading={chat.loading}
          chatId={chat.chatId}
        />
      )}
    </main>
  );
}
