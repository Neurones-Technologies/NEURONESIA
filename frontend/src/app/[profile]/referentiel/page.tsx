import { notFound } from "next/navigation";
import { View } from "@/components/shell/AppShell";
import { getMe } from "@/lib/api/me";
import { isAdminRole } from "@/lib/auth/roles";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { DonneesView } from "@/components/views/DonneesView";

/** Réservé à l'administrateur : la vue expose l'effectif et la fraîcheur brute
 * du miroir (`/v1/stats/mirror`), une lecture d'infrastructure et non un
 * module métier. Vérifié ici (pas seulement masqué dans le rail) — l'endpoint
 * backend applique le même contrôle. */
export default async function DonneesPage({ params }: { params: Promise<{ profile: string }> }) {
  const { profile } = await params;
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;

  const me = await getMe();
  if (!isAdminRole(me.role)) notFound();

  return (
    <View>
      <DonneesView profile={key} />
    </View>
  );
}
