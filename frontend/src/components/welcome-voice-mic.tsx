"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Mic, MicOff } from "lucide-react";
import { IconButton } from "@openuidev/react-ui";
import { useThreadList } from "@openuidev/react-headless";
import { useRealtimeVoice } from "@/hooks/use-realtime-voice";

/**
 * Injects a mic control into the OpenUI welcome-screen composer action bar.
 */
export function WelcomeVoiceMic({
  userId,
  voiceEnabled,
}: {
  userId: string;
  voiceEnabled: boolean;
}) {
  const [host, setHost] = useState<Element | null>(null);
  const selectedThreadId = useThreadList((s) => s.selectedThreadId);
  const voice = useRealtimeVoice({ userId, enabled: voiceEnabled });

  useEffect(() => {
    const findBar = () =>
      document.querySelector(".openui-agent-desktop-welcome-composer__action-bar");
    setHost(findBar());
    const observer = new MutationObserver(() => setHost(findBar()));
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  if (!host) return null;

  const micDisabled = !voiceEnabled || !selectedThreadId;

  return createPortal(
    <div className="flyt-welcome-voice-wrap">
      <IconButton
        onClick={() => void voice.toggle()}
        disabled={micDisabled}
        icon={voice.active ? <MicOff size="1em" /> : <Mic size="1em" />}
        size="small"
        variant={voice.active ? "primary" : "secondary"}
        aria-pressed={voice.active}
        aria-label={voice.active ? "Stop voice mode" : "Start voice mode"}
        className="flyt-composer-mic-button"
      />
    </div>,
    host,
  );
}
