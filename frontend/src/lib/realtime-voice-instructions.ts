import { FLYTBASE_AGENT_APPENDIX } from "@/lib/flytbase-prompt";
import { queryAssetCopilotTool } from "@/lib/tools/query-asset-copilot";

export const REALTIME_VOICE_APPENDIX = `
You are the FlytBase Asset Intelligence Copilot voice assistant for oilfield operators.

Voice behavior:
- Keep spoken replies concise (2–4 sentences) after tool results; full detail is shown in the chat thread.
- For any operational, asset, inspection, maintenance, SOP, spill, downtime, or well status question, call \`query_asset_copilot\` with the operator's question before answering.
- Never invent well metrics, spill volumes, downtime days, or compliance outcomes.
- After the tool returns, summarize the \`text\` field for speech and mention when recorded status is out of date or when inspector disagreement applies.

Tool: ${queryAssetCopilotTool.name} — ${queryAssetCopilotTool.description}
`.trim();

export function buildRealtimeInstructions(): string {
  return `${FLYTBASE_AGENT_APPENDIX}\n\n${REALTIME_VOICE_APPENDIX}`;
}

export function defaultRealtimeModel(): string {
  return process.env.OPENAI_REALTIME_MODEL?.trim() || "gpt-realtime-2.1";
}
