/** All non-logic values: brand, copy, environment and feature flags. */

export const config = {
  brandName: "Rubies MFB Support",
  brandShortName: "Rubies",
  brandDescription: "AI-powered customer service for Rubies MFB",
  logoLetter: "R",
  panelEnabled: true,
  apiUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8002",
  demoOtp: process.env.NEXT_PUBLIC_DEMO_OTP === "true",
  transport:
    process.env.NEXT_PUBLIC_TRANSPORT === "mock"
      ? ("mock" as const)
      : ("http" as const),
} as const;

export const starterPrompts = [
  "What is the fee for transfers above ₦50,000?",
  "I lost my card, please block it",
  "Abeg, my money no gree enter o",
] as const;

export const quickReplies = ["Yes, go ahead", "Cancel"] as const;

export const copy = {
  chat: {
    brand: "Rubies MFB Support",
    sessionButton: "Session",
    newChatButton: "New chat",
    demoOtpButton: "Demo OTP",
    demoOtpAria: "Show demo OTP",
    demoOtpLabel: "Demo OTP · Development only",
    restoring: "Restoring your chat…",
    emptyTitle: "How can we help?",
    emptyBody:
      "Ask about fees, cards, transfers or loans. For account tasks I’ll verify you first.",
    thinking: "Thinking…",
    stopped: "Stopped.",
    interrupted: "Reply interrupted.",
    retry: "Retry",
    userAria: "Your message",
    agentAria: "Rubies reply",
    verificationExpired:
      "Your verification ended. This chat will clear when you send your next message or refresh.",
    incomplete: "This reply may be incomplete.",
    inputBusy: "Rubies is replying…",
    inputIdle: "Message Rubies support",
    messageAria: "Message",
    safety:
      "Rubies will never ask for your PIN, password or full card number in chat.",
    sources: "Sources checked",
  },
  steps: {
    aria: "What the agent did",
    title: "What I did",
    step: "step",
    steps: "steps",
    hide: "Hide",
    show: "Show",
  },
  panel: {
    title: "Session",
    aria: "Session",
    closeAria: "Close session panel",
    sessionTitle: "Session",
    verified: "Verified",
    notVerified: "Not verified yet",
    expiresPrefix: "Expires in ",
    expired: "Session expired. Verify again to continue.",
    endChat: "End chat and clear",
    notSaved: "Messages and account details are not saved.",
    referencesTitle: "Your references",
    referencesEmpty:
      "References from this chat, such as dispute numbers, will appear here.",
    saveCopy: "Save a copy",
    handoffTitle: "Human handoff",
    handoffBody: "A human agent has your ticket",
    sharedWithAgent: "What we shared with the agent",
    tasksTitle: "Common tasks",
    safetyTitle: "Stay safe",
    safetyStorage:
      "Only a temporary chat ID is kept in this tab. Ending the chat clears it. Messages and account details are not saved.",
    safetyPin:
      "Rubies will never ask for your PIN, password or full card number.",
    copy: "Copy",
    copied: "Copied",
    copyAria: "Copy ",
    referencesFileTitle: "Rubies MFB references",
    savedPrefix: "Saved ",
    referencePrefix: "Reference: ",
    referencesFileName: "rubies-references",
    copyReference: "reference",
    copyTicket: "ticket reference",
  },
  tasks: [
    { label: "Block a lost card", message: "I lost my card, please block it" },
    {
      label: "Report a failed or double debit",
      message: "I think a transfer failed or I was debited twice",
    },
    {
      label: "Check loan eligibility",
      message: "Can I check if I qualify for a loan?",
    },
    { label: "Talk to a person", message: "I want to speak to a human agent" },
  ],
  errors: {
    emptyMessage: "Please enter a message.",
    tooLong: "That message is too long. Please shorten it.",
    sendFailed: "That message couldn’t be sent. Please try again.",
    expiredNotice: "Your session ended. Started a new chat.",
    newChatFailed: "Couldn’t start a new chat. Please refresh the page.",
    startChatPrefix: "Failed to start chat: ",
    unknown: "unknown",
    restoreFailed: "Couldn’t restore your chat. Please retry.",
    generic: "Something went wrong.",
  },
} as const;
