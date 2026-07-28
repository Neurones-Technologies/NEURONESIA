import { NextResponse } from "next/server";
import { BACKEND_URL } from "@/lib/api/client";
import { roleToProfile } from "@/lib/auth/roles";

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
  const response = NextResponse.json({
    role: data.user.role,
    profile: roleToProfile(data.user.role),
    fullName: data.user.full_name,
  });

  const cookieOpts = {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge: SESSION_MAX_AGE,
  };
  response.cookies.set("session", data.access_token, cookieOpts);
  response.cookies.set("role", data.user.role, cookieOpts);

  return response;
}
