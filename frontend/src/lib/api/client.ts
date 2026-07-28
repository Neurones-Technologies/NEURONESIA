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

  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...rest,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(rest.body ? { "Content-Type": "application/json" } : {}),
      ...rest.headers,
    },
    cache: "no-store",
  });

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
