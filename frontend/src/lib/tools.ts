import {
  executeQueryAssetCopilot,
  queryAssetCopilotTool,
} from "@/lib/tools/query-asset-copilot";
import { tool } from "ai";
import { z } from "zod";

export const appTools = {
  query_asset_copilot: tool({
    description: queryAssetCopilotTool.description,
    inputSchema: z.object({
      query: z
        .string()
        .trim()
        .min(1)
        .describe("Operator question about wells, inspections, maintenance, or SOPs."),
      user_id: z.string().optional().describe("Operator user id, default U-201."),
      session_id: z.string().optional().describe("Chat session id for GateMem isolation."),
    }),
    execute: ({ query, user_id, session_id }, { abortSignal }) =>
      executeQueryAssetCopilot(JSON.stringify({ query, user_id, session_id }), {
        signal: abortSignal,
      }),
  }),
} as const;

export const appToolNames = new Set(Object.keys(appTools));
