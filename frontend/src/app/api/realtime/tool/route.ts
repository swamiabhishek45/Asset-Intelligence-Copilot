import { executeQueryAssetCopilot } from "@/lib/tools/query-asset-copilot";
import type { VoiceThreadPayload } from "@/lib/voice-thread-sync";

export const runtime = "nodejs";

type ToolRequest = {
  name?: string;
  arguments?: Record<string, unknown> | string;
  userId?: string;
  threadId?: string;
};

export async function POST(req: Request) {
  const body = (await req.json()) as ToolRequest;
  const name = typeof body.name === "string" ? body.name.trim() : "";
  const userId = typeof body.userId === "string" ? body.userId.trim() : "U-201";
  const threadId = typeof body.threadId === "string" ? body.threadId.trim() : "frontend-session";

  if (!name) {
    return Response.json({ error: { message: "name is required" } }, { status: 400 });
  }

  if (name !== "query_asset_copilot") {
    return Response.json({ error: { message: `Unknown tool: ${name}` } }, { status: 400 });
  }

  let args: Record<string, unknown> = {};
  if (typeof body.arguments === "string") {
    try {
      args = JSON.parse(body.arguments) as Record<string, unknown>;
    } catch {
      args = { query: body.arguments };
    }
  } else if (body.arguments && typeof body.arguments === "object") {
    args = body.arguments;
  }

  const query = typeof args.query === "string" ? args.query.trim() : "";
  if (!query) {
    return Response.json({ error: { message: "query is required" } }, { status: 400 });
  }

  const payload = {
    query,
    user_id: typeof args.user_id === "string" ? args.user_id : userId,
    session_id: typeof args.session_id === "string" ? args.session_id : threadId,
  };

  try {
    const result = await executeQueryAssetCopilot(JSON.stringify(payload));
    const threadPayload: VoiceThreadPayload = {
      userText: query,
      assistantText: result.text,
      openui_visual: result.openui_visual ?? null,
    };

    const toolResult = {
      text: result.text,
      visual_type: result.visual_type,
      citations: result.citations,
      speakable_summary: result.text.slice(0, 1200),
    };

    return Response.json({ toolResult, threadPayload });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Tool execution failed";
    return Response.json({ error: { message } }, { status: 502 });
  }
}
