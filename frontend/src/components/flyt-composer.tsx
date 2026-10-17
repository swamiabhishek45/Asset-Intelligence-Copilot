"use client";

import React, { useCallback, useLayoutEffect, useRef, useState } from "react";
import { ArrowUp, Mic, MicOff, Square } from "lucide-react";
import { IconButton, useLayoutContext } from "@openuidev/react-ui";
import { useThread, useThreadList } from "@openuidev/react-headless";
import { cn } from "@/lib/utils";
import { useRealtimeVoice } from "@/hooks/use-realtime-voice";

type FlytComposerProps = {
  userId: string;
  voiceEnabled: boolean;
  placeholder?: string;
  className?: string;
};

function shouldSubmitOnEnter(event: React.KeyboardEvent<HTMLTextAreaElement>) {
  if (event.key !== "Enter" || event.shiftKey) return false;
  return !event.nativeEvent.isComposing && event.keyCode !== 229;
}

export function FlytComposer({
  userId,
  voiceEnabled,
  placeholder = "Ask anything...",
  className,
}: FlytComposerProps) {
  const [textContent, setTextContent] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [hasInputOverflowTop, setHasInputOverflowTop] = useState(false);
  const [hasInputOverflowBottom, setHasInputOverflowBottom] = useState(false);

  const processMessage = useThread((s) => s.processMessage);
  const cancelMessage = useThread((s) => s.cancelMessage);
  const isRunning = useThread((s) => s.isRunning);
  const isLoadingMessages = useThread((s) => s.isLoadingMessages);
  const selectedThreadId = useThreadList((s) => s.selectedThreadId);
  const { layout } = useLayoutContext();

  const voice = useRealtimeVoice({ userId, enabled: voiceEnabled });

  const updateInputOverflow = useCallback(() => {
    const input = inputRef.current;
    if (!input) return;
    const maxScrollTop = input.scrollHeight - input.clientHeight;
    setHasInputOverflowTop(maxScrollTop > 0 && input.scrollTop > 0);
    setHasInputOverflowBottom(maxScrollTop > 0 && input.scrollTop < maxScrollTop - 1);
  }, []);

  const handleSubmit = () => {
    if (!textContent.trim() || isRunning || isLoadingMessages) return;
    if (voice.active) void voice.disconnect();
    processMessage({
      role: "user",
      content: textContent,
    });
    setTextContent("");
  };

  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.style.height = "0px";
    input.style.height = `${Math.max(input.scrollHeight, 32)}px`;
    updateInputOverflow();
  }, [textContent, updateInputOverflow]);

  useLayoutEffect(() => {
    if (layout === "mobile" || isLoadingMessages) return;
    inputRef.current?.focus();
  }, [layout, isLoadingMessages, selectedThreadId]);

  const micDisabled = !voiceEnabled || isRunning || isLoadingMessages || !selectedThreadId;

  return (
    <div
      className={cn("openui-agent-thread-composer flyt-thread-composer", className)}
      data-drafting={textContent.length > 0 || undefined}
      data-voice-active={voice.active || undefined}
      onClick={(e) => {
        const target = e.target;
        if (
          target instanceof Element &&
          !target.closest("button, a, [role='button']")
        ) {
          inputRef.current?.focus();
        }
      }}
    >
      {voice.active && voice.statusLabel ? (
        <p className="flyt-voice-status" aria-live="polite">
          {voice.statusLabel}
        </p>
      ) : null}
      {voice.error ? (
        <p className="flyt-voice-error" role="alert">
          {voice.error}
        </p>
      ) : null}
      <div
        className="openui-agent-thread-composer__input-wrapper"
        data-overflow-top={hasInputOverflowTop || undefined}
        data-overflow-bottom={hasInputOverflowBottom || undefined}
      >
        <textarea
          ref={inputRef}
          value={textContent}
          autoFocus
          onChange={(e) => setTextContent(e.target.value)}
          onScroll={updateInputOverflow}
          className="openui-agent-thread-composer__input"
          placeholder={placeholder}
          rows={1}
          disabled={voice.active && voice.status === "connecting"}
          onKeyDown={(e) => {
            if (shouldSubmitOnEnter(e)) {
              e.preventDefault();
              handleSubmit();
            }
          }}
        />
        <div className="openui-agent-thread-composer__action-bar flyt-composer-action-bar">
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
          <IconButton
            onClick={isRunning ? cancelMessage : handleSubmit}
            icon={
              isRunning ? (
                <Square size="1em" fill="currentColor" />
              ) : (
                <ArrowUp size="1em" />
              )
            }
            size="small"
            variant="primary"
            aria-label={isRunning ? "Cancel message" : "Send message"}
            className="openui-agent-thread-composer__submit-button"
            disabled={!textContent.trim() && !isRunning}
          />
        </div>
      </div>
    </div>
  );
}
