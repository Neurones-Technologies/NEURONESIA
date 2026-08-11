import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { ReactNode } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { ApiError } from "@/lib/api/client";
import { getMe, type Me } from "@/lib/api/me";
import { ROLE_LABELS, isAdminRole, roleToProfile } from "@/lib/auth/roles";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";

function initials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export default async function ProfileLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ profile: string }>;
}) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();

  const store = await cookies();
  if (!store.get("session")?.value) redirect("/login");

  let me: Me;
  try {
    me = await getMe();
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) redirect("/login");
    throw err;
  }

  const admin = isAdminRole(me.role);
  const ownProfile = roleToProfile(me.role);

  // Un compte non-admin est toujours ramené à son propre profil — l'auth réelle
  // remplace le sélecteur libre de la maquette (un seul persona par session).
  if (!admin && ownProfile && profile !== ownProfile) {
    redirect(`/${ownProfile}/vision`);
  }
  if (!admin && !ownProfile) {
    // Rôle sans profil cockpit dédié (presale, user, viewer) — pas de session utilisable ici.
    redirect("/login");
  }

  const shellUser = {
    code: initials(me.full_name),
    fullName: me.full_name,
    roleLabel: ROLE_LABELS[me.role] ?? me.role,
    isAdmin: admin,
  };

  return (
    <AppShell profile={profile as ProfileKey} user={shellUser}>
      {children}
    </AppShell>
  );
}
