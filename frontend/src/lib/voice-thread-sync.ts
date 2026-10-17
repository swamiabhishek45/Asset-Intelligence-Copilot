import type { AssistantMessage, Message, UserMessage } from "@openuidev/react-headless";

export type VoiceThreadPayload = {
  userText?: string;
  assistantText: string;
  openui_visual?: string | null;
};

export function buildVoiceTurnMessages(payload: VoiceThreadPayload): Message[] {
  const userText = payload.userText?.trim() || "(Voice question)";
  const assistantContent =
    payload.openui_visual?.trim() || payload.assistantText?.trim() || "No response from copilot.";

  const userMsg: UserMessage = {
    id: crypto.randomUUID(),
    role: "user",
    content: userText,
  };

  const assistantMsg: AssistantMessage = {
    id: crypto.randomUUID(),
    role: "assistant",
    content: assistantContent,
  };

  return [userMsg, assistantMsg];
}
