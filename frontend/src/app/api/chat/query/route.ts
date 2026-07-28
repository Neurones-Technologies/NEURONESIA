import { BACKEND_URL, getSessionToken } from "@/lib/api/client";

/** Proxy SSE : le navigateur ne peut pas poser le header Authorization sur le
 * flux backend (token httpOnly) — ce handler rejoue la requête multipart côté
 * serveur et repasse le flux `text/event-stream` tel quel, sans le bufferiser. */
export async function POST(request: Request) {
  const token = await getSessionToken();
  if (!token) {
    return new Response(JSON.stringify({ detail: "Non authentifié" }), { status: 401 });
  }

  const formData = await request.formData();

  const backendRes = await fetch(`${BACKEND_URL}/v1/chat/query`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });

  if (!backendRes.ok || !backendRes.body) {
    const detail = await backendRes.text().catch(() => "Échec de la requête");
    return new Response(JSON.stringify({ detail }), { status: backendRes.status || 502 });
  }

  return new Response(backendRes.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
