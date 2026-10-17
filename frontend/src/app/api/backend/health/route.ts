import { envOr } from "@/lib/env";

export const runtime = "nodejs";

const BACKEND_URL = envOr("BACKEND_API_URL", "http://127.0.0.1:8000");

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/health`, {
      next: { revalidate: 0 },
    });
    const body = await response.text();
    return new Response(body, {
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
