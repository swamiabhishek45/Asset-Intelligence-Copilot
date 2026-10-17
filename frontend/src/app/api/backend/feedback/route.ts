import { envOr } from "@/lib/env";

export const runtime = "nodejs";

const BACKEND_URL = envOr("BACKEND_URL", envOr("BACKEND_API_URL", "http://127.0.0.1:8000"));

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const response = await fetch(`${BACKEND_URL}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.text();
    return new Response(data, {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    return Response.json(
      { status: "unreachable", error: error instanceof Error ? error.message : "unknown" },
      { status: 502 },
    );
  }
}
