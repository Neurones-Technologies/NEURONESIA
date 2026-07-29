import { notFound } from "next/navigation";
import { View } from "@/components/shell/AppShell";
import { apiFetch } from "@/lib/api/client";
import { isAdminRole } from "@/lib/auth/roles";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { DonneesView } from "@/components/views/DonneesView";

interface Me {
  role: string;
}

/** Réservé à l'administrateur : la vue expose l'effectif et la fraîcheur brute
 * du miroir (`/v1/stats/mirror`), une lecture d'infrastructure et non un
 * module métier. Vérifié ici (pas seulement masqué dans le rail) — l'endpoint
 * backend applique le même contrôle. */
export default async function DonneesPage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;

  const me = await apiFetch<Me>("/v1/auth/me");
  if (!isAdminRole(me.role)) notFound();

  return (
    <View>
      <DonneesView profile={key} />
    </View>
  );
}
