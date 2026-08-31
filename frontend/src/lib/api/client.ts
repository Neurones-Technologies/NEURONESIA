import { cookies } from "next/headers";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export async function getSessionToken(): Promise<string | null> {
  const store = await cookies();
  return store.get("session")?.value ?? null;
}

interface ApiFetchInit extends RequestInit {
  /** Ignore un 403 (accès refusé par le rôle) et renvoie `null` au lieu de lever. */
  allowForbidden?: boolean;
}

export async function apiFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const token = await getSessionToken();
  const { allowForbidden, ...rest } = init;

  let res: Response;
  try {
    res = await fetch(`${BACKEND_URL}${path}`, {
      ...rest,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(rest.body ? { "Content-Type": "application/json" } : {}),
        ...rest.headers,
      },
      cache: "no-store",
    });
  } catch (cause) {
    // Panne au niveau connexion, AVANT toute réponse HTTP : backend éteint, ou
    // fenêtre de redémarrage d'uvicorn --reload pendant l'édition d'un fichier
    // backend. `fetch` lève alors un TypeError « fetch failed » dont le message
    // ne dit NI l'URL visée NI la raison, et qui fait tomber tout le rendu
    // serveur sur « A server error occurred » : illisible, et impossible à
    // distinguer d'un bug applicatif. On le retraduit en ApiError 503 nommant la
    // cible, pour que le message dise quoi relancer.
    //
    // Pas de retry ici : `apiFetch` sert aussi les mutations (POST/PATCH/DELETE
    // des Server Actions), et rejouer une écriture dont on ignore si elle a été
    // reçue côté serveur est pire que l'échec.
    const detail = cause instanceof Error && cause.cause instanceof Error
      ? cause.cause.message
      : cause instanceof Error
        ? cause.message
        : String(cause);
    throw new ApiError(503, `Backend injoignable sur ${BACKEND_URL} (${path}) : ${detail}`);
  }

  if (res.status === 403 && allowForbidden) {
    return null as T;
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // réponse non-JSON — on garde statusText
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return null as T;
  return res.json() as Promise<T>;
}

export { BACKEND_URL };
