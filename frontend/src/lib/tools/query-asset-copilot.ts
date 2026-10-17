import { envOr } from "@/lib/env";
import { buildCopilotVisualProgram } from "@/lib/visuals/to-openui-lang";

const BACKEND_URL = envOr("BACKEND_URL", envOr("BACKEND_API_URL", "http://127.0.0.1:8000"));

export type CopilotQueryResult = {
  text: string;
  visual_type: string;
  visual_payload: Record<string, unknown>;
  citations: string[];
  pipeline_telemetry?: Record<string, unknown>;
  /** Pre-built OpenUI Lang program derived from visual_type + visual_payload. */
  openui_visual?: string | null;
};

export const queryAssetCopilotTool = {
  name: "query_asset_copilot",
  description:
    "Query the FlytBase Asset Intelligence backend (GateMem, domain tools, RCN+CNN+HTGNN). Use for well status, inspections, maintenance, SOPs, downtime, thermal readings, and benchmark evaluation questions. Pass the operator's question verbatim.",
};

export async function executeQueryAssetCopilot(
  input: string,
  options?: { signal?: AbortSignal },
): Promise<CopilotQueryResult> {
  let query: string;
  let user_id = "U-201";
  let session_id = "frontend-session";

  try {
    const parsed = JSON.parse(input) as {
      query?: string;
      user_id?: string;
      session_id?: string;
    };
    query = (parsed.query ?? input).trim();
    if (parsed.user_id) user_id = parsed.user_id;
    if (parsed.session_id) session_id = parsed.session_id;
  } catch {
    query = input.trim();
  }

  if (!query) {
    throw new Error("query is required");
  }

  const response = await fetch(`${BACKEND_URL}/api/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, user_id, session_id }),
    signal: options?.signal,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Backend /api/query failed (${response.status}): ${body}`);
  }

  const body = (await response.json()) as CopilotQueryResult;
  const openui_visual = buildCopilotVisualProgram(
    {
      text: body.text,
      visual_type: body.visual_type,
      visual_payload: body.visual_payload ?? {},
      citations: body.citations,
    },
    query,
  );

  return { ...body, openui_visual };
}
