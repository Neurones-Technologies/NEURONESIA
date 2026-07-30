import { NextResponse } from "next/server";
import { apiFetch, ApiError } from "@/lib/api/client";

export interface SessionSummary {
  session_id: string;
  title: string;
  started_at: string | null;
  last_at: string | null;
  turn_count: number;
}

/** Liste des conversations du Copilote pour l'utilisateur connecté, cloisonnée
 * par profil cockpit. Route client (le composant ChatBox rafraîchit la liste
 * après chaque échange), d'où le proxy : le token est en cookie httpOnly. */
export async function GET(request: Request) {
  const profile = new URL(request.url).searchParams.get("profile") ?? "";
  try {
    const data = await apiFetch<{ sessions: SessionSummary[] }>(
      `/v1/chat/sessions?profile=${encodeURIComponent(profile)}`
    );
    return NextResponse.json(data);
  } catch (err) {
    const status = err instanceof ApiError ? err.status : 502;
    const detail = err instanceof ApiError ? err.detail : "Historique indisponible";
    return NextResponse.json({ detail }, { status });
  }
}
