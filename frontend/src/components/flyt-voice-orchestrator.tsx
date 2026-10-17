"use client";

import { WelcomeVoiceMic } from "@/components/welcome-voice-mic";

/** Rendered via AgentInterface `rest` slot (direct child). */
export function FlytVoiceOrchestrator({
  userId,
  voiceEnabled,
}: {
  userId: string;
  voiceEnabled: boolean;
}) {
  return <WelcomeVoiceMic userId={userId} voiceEnabled={voiceEnabled} />;
}
