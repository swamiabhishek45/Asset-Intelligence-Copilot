export const runtime = "nodejs";

export async function GET() {
  return Response.json({
    enabled: Boolean(process.env.OPENAI_API_KEY?.trim()),
    model: process.env.OPENAI_REALTIME_MODEL?.trim() || "gpt-realtime-2.1",
  });
}
