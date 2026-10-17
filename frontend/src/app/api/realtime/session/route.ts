import { buildRealtimeInstructions, defaultRealtimeModel } from "@/lib/realtime-voice-instructions";
import { queryAssetCopilotTool } from "@/lib/tools/query-asset-copilot";
import { envOr, requiredEnv } from "@/lib/env";

export const runtime = "nodejs";

type SessionRequest = {
  threadId?: string;
  userId?: string;
  model?: string;
};

export async function POST(req: Request) {
  let apiKey: string;
  try {
    apiKey = requiredEnv("OPENAI_API_KEY");
  } catch {
    return Response.json(
      { error: { message: "OPENAI_API_KEY is not configured on the frontend server." } },
      { status: 503 },
    );
  }

  const body = (await req.json()) as SessionRequest;
  const threadId = typeof body.threadId === "string" ? body.threadId.trim() : "";
  const userId = typeof body.userId === "string" ? body.userId.trim() : "U-201";
  const model =
    typeof body.model === "string" && body.model.trim() ? body.model.trim() : defaultRealtimeModel();

  if (!threadId) {
    return Response.json({ error: { message: "threadId is required" } }, { status: 400 });
  }

  const instructions = `${buildRealtimeInstructions()}\n\nActive operator user_id: ${userId}. Active session_id (GateMem): ${threadId}.`;

  const session = {
    type: "realtime",
    model,
    instructions,
    output_modalities: ["audio", "text"],
    audio: {
      output: {
        voice: envOr("OPENAI_REALTIME_VOICE", "marin"),
      },
    },
    tools: [
      {
        type: "function",
        name: "query_asset_copilot",
        description: queryAssetCopilotTool.description,
        parameters: {
          type: "object",
          properties: {
            query: {
              type: "string",
              description:
                "Operator question about wells, inspections, maintenance, or SOPs (verbatim).",
            },
            user_id: {
              type: "string",
              description: "Operator user id for GateMem.",
            },
            session_id: {
              type: "string",
              description: "Chat thread id for GateMem isolation.",
            },
          },
          required: ["query"],
        },
      },
    ],
  };

  const response = await fetch("https://api.openai.com/v1/realtime/client_secrets", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      "OpenAI-Safety-Identifier": userId,
    },
    body: JSON.stringify({ session }),
  });

  if (!response.ok) {
    const detail = await response.text();
    return Response.json(
      { error: { message: `Failed to create Realtime session (${response.status})`, detail } },
      { status: 502 },
    );
  }

  const data = (await response.json()) as { value?: string };
  if (!data.value) {
    return Response.json({ error: { message: "Realtime client secret missing value" } }, { status: 502 });
  }

  return Response.json({ value: data.value, model });
}
