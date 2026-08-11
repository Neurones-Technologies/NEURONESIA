import { NextResponse } from "next/server";
import { apiFetch, ApiError } from "@/lib/api/client";

interface StoredMessage {
  role: "user" | "assistant";
  content: string;
}

function errorResponse(err: unknown, fallback: string) {
  const status = err instanceof ApiError ? err.status : 502;
  const detail = err instanceof ApiError ? err.detail : fallback;
  return NextResponse.json({ detail }, { status });
}

/** Le backend renvoie `messages: []` (200) aussi bien pour un fil purgé que pour
 * un profil non reconnu (cf. router.py, get_session_history). Sans ce marqueur le
 * client ne peut pas distinguer « ce fil n'existe plus » — qui justifie d'oublier
 * le pointeur localStorage — d'un simple aléa, qui ne le justifie pas. */
const EMPTY_HISTORY_HEADER = "x-history-empty";

/** Historique complet d'une conversation, pour la reprendre. */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params;
  const profile = new URL(request.url).searchParams.get("profile") ?? "";
  try {
    const data = await apiFetch<{ session_id: string; messages: StoredMessage[] }>(
      `/v1/chat/sessions/${encodeURIComponent(sessionId)}?profile=${encodeURIComponent(profile)}`
    );
    return NextResponse.json(data, {
      headers: data.messages?.length ? undefined : { [EMPTY_HISTORY_HEADER]: "1" },
    });
  } catch (err) {
    return errorResponse(err, "Conversation introuvable");
  }
}

/** Suppression d'une conversation. Côté backend la route est au singulier
 * (`/v1/chat/session/{id}`) — on garde `/sessions/{id}` côté client pour que la
 * ressource ait une seule adresse dans le frontend. */
export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params;
  const profile = new URL(request.url).searchParams.get("profile") ?? "";
  try {
    const data = await apiFetch<{ status: string; session_id: string }>(
      `/v1/chat/session/${encodeURIComponent(sessionId)}?profile=${encodeURIComponent(profile)}`,
      { method: "DELETE" }
    );
    return NextResponse.json(data);
  } catch (err) {
    return errorResponse(err, "Suppression impossible");
  }
}
