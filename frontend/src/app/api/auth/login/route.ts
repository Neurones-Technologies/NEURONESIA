import { NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/api/client";
import { isAdminRole, roleToProfile } from "@/lib/auth/roles";

const SESSION_MAX_AGE = 12 * 60 * 60; // 12h — aligné sur settings.jwt_expire_hours côté backend

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  if (!body?.email || !body?.password) {
    return NextResponse.json({ detail: "Email et mot de passe requis" }, { status: 422 });
  }

  const backendRes = await fetch(`${BACKEND_URL}/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: body.email, password: body.password }),
  });

  if (!backendRes.ok) {
    const data = await backendRes.json().catch(() => ({}));
    return NextResponse.json(
      { detail: data.detail || "Échec de connexion" },
      { status: backendRes.status }
    );
  }

  const data = await backendRes.json();

  // Les identifiants sont bons, mais tous les rôles n'ont pas de cockpit :
  // `presale`, `user` et `viewer` n'ont aucune route [profile] à eux. Sans ce
  // contrôle la session est bien posée, puis le layout [profile] renvoie sur
  // /login — l'utilisateur voit un formulaire qui « ne fait rien » alors qu'il
  // est authentifié. On refuse ici, avec la raison. L'admin (profile null) a
  // accès à tous les cockpits via le sélecteur du UserMenu : il passe.
  const profile = roleToProfile(data.user.role);
  if (!profile && !isAdminRole(data.user.role)) {
    return NextResponse.json(
      {
        detail:
          "Aucun cockpit n'est associé à ce profil — contactez un administrateur.",
      },
      { status: 403 }
    );
  }

  const response = NextResponse.json({
    role: data.user.role,
    profile,
    fullName: data.user.full_name,
  });

  // `secure` suit le protocole REEL de la requête (X-Forwarded-Proto injecté par
  // nginx), pas NODE_ENV : en prod sur HTTP nu (accès par IP, pas de certificat
  // possible pour une IP), un cookie Secure est purement et simplement ignoré par
  // le navigateur → session jamais posée, le middleware renvoie en boucle sur
  // /login et la connexion « ne fait rien ». Bug réel rencontré. Dès que le site
  // passera derrière HTTPS, l'attribut se réactive tout seul.
  const forwardedProto = request.headers.get("x-forwarded-proto");
  const isHttps = forwardedProto
    ? forwardedProto.split(",")[0].trim() === "https"
    : new URL(request.url).protocol === "https:";

  const cookieOpts = {
    httpOnly: true,
    secure: isHttps,
    sameSite: "lax" as const,
    path: "/",
    maxAge: SESSION_MAX_AGE,
  };
  response.cookies.set("session", data.access_token, cookieOpts);
  response.cookies.set("role", data.user.role, cookieOpts);

  return response;
}
