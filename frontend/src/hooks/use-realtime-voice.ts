"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { RealtimeAgent, RealtimeSession, tool } from "@openai/agents/realtime";
import { useThread, useThreadList } from "@openuidev/react-headless";
import { z } from "zod";
import { buildRealtimeInstructions } from "@/lib/realtime-voice-instructions";
import { queryAssetCopilotTool } from "@/lib/tools/query-asset-copilot";
import {
  buildVoiceTurnMessages,
  type VoiceThreadPayload,
} from "@/lib/voice-thread-sync";

export type RealtimeVoiceStatus = "idle" | "connecting" | "listening" | "speaking" | "error";

type UseRealtimeVoiceOptions = {
  userId: string;
  enabled: boolean;
};

export function useRealtimeVoice({ userId, enabled }: UseRealtimeVoiceOptions) {
  const [active, setActive] = useState(false);
  const [status, setStatus] = useState<RealtimeVoiceStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const sessionRef = useRef<RealtimeSession | null>(null);
  const syncedTurnIdsRef = useRef<Set<string>>(new Set());

  const appendMessages = useThread((s) => s.appendMessages);
  const selectedThreadId = useThreadList((s) => s.selectedThreadId);

  const syncThread = useCallback(
    (payload: VoiceThreadPayload, dedupeKey?: string) => {
      const key = dedupeKey ?? `${payload.userText ?? ""}:${payload.assistantText.slice(0, 64)}`;
      if (syncedTurnIdsRef.current.has(key)) return;
      syncedTurnIdsRef.current.add(key);
      appendMessages(...buildVoiceTurnMessages(payload));
    },
    [appendMessages],
  );

  const disconnect = useCallback(async () => {
    const session = sessionRef.current;
    sessionRef.current = null;
    setActive(false);
    if (session) {
      try {
        session.close();
      } catch {
        /* ignore */
      }
    }
    setStatus("idle");
  }, []);

  const connect = useCallback(async () => {
    if (!enabled) {
      setError("Voice requires OPENAI_API_KEY on the frontend server.");
      setStatus("error");
      return;
    }

    const threadId = selectedThreadId;
    if (!threadId) {
      setError("Select or start a chat thread before using voice.");
      setStatus("error");
      return;
    }

    setError(null);
    setStatus("connecting");

    try {
      const tokenRes = await fetch("/api/realtime/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threadId, userId }),
      });

      if (!tokenRes.ok) {
        const body = (await tokenRes.json().catch(() => ({}))) as { error?: { message?: string } };
        throw new Error(body.error?.message ?? `Session request failed (${tokenRes.status})`);
      }

      const { value: apiKey } = (await tokenRes.json()) as { value: string };

      const queryTool = tool({
        name: "query_asset_copilot",
        description: queryAssetCopilotTool.description,
        parameters: z.object({
          query: z.string().min(1),
          user_id: z.string().optional(),
          session_id: z.string().optional(),
        }),
        execute: async (input) => {
          const res = await fetch("/api/realtime/tool", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: "query_asset_copilot",
              arguments: input,
              userId,
              threadId,
            }),
          });

          if (!res.ok) {
            const body = (await res.json().catch(() => ({}))) as { error?: { message?: string } };
            throw new Error(body.error?.message ?? `Tool failed (${res.status})`);
          }

          const data = (await res.json()) as {
            toolResult: Record<string, unknown>;
            threadPayload: VoiceThreadPayload;
          };

          syncThread(data.threadPayload, `tool:${input.query}`);
          return JSON.stringify(data.toolResult);
        },
      });

      const agent = new RealtimeAgent({
        name: "FlytBase Asset Copilot",
        instructions: buildRealtimeInstructions(),
        tools: [queryTool],
        voice: "marin",
      });

      const session = new RealtimeSession(agent, { transport: "webrtc" });
      sessionRef.current = session;

      session.on("audio_start", () => setStatus("speaking"));
      session.on("audio_stopped", () => setStatus("listening"));
      session.on("agent_tool_end", (_ctx, _agent, _tool, result) => {
        if (typeof result === "string" && result.length > 0) {
          /* thread sync handled in tool execute */
        }
      });
      session.on("transport_event", (event) => {
        if (event.type === "conversation.item.input_audio_transcription.completed") {
          const transcript = (event as { transcript?: string }).transcript?.trim();
          if (transcript) {
            /* stored when tool runs with query text */
          }
        }
      });
      session.on("error", (payload) => {
        const message =
          payload && typeof payload === "object" && "error" in payload
            ? String((payload as { error: unknown }).error)
            : "Realtime session error";
        setError(message);
        setStatus("error");
      });

      await session.connect({ apiKey });
      setActive(true);
      setStatus("listening");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to start voice session";
      setError(message);
      setStatus("error");
      await disconnect();
    }
  }, [disconnect, enabled, selectedThreadId, syncThread, userId]);

  const toggle = useCallback(async () => {
    if (active) {
      await disconnect();
      return;
    }
    await connect();
  }, [active, connect, disconnect]);

  useEffect(() => {
    if (!active) return;
    return () => {
      void disconnect();
    };
  }, [active, disconnect]);

  useEffect(() => {
    if (active) void disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reconnect required on thread/user change
  }, [selectedThreadId, userId]);

  return {
    active,
    status,
    error,
    toggle,
    disconnect,
    statusLabel:
      status === "connecting"
        ? "Connecting…"
        : status === "listening"
          ? "Listening…"
          : status === "speaking"
            ? "Speaking…"
            : status === "error"
              ? "Voice error"
              : "",
  };
}
