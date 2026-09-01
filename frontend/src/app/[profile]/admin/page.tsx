import { notFound } from "next/navigation";
import { View } from "@/components/shell/AppShell";
import { getMe } from "@/lib/api/me";
import { isAdminRole } from "@/lib/auth/roles";
import { PROFILE_KEYS, ProfileKey } from "@/lib/types";
import { AdminView } from "@/components/views/AdminView";

/** Écran Comptes — réservé à l'administrateur.
 *
 * Le contrôle est fait ICI, et pas seulement par le masquage de l'entrée du rail :
 * une URL tapée à la main atteindrait la page. Il est refait côté backend sur
 * chaque endpoint (`_require_admin`), ce qui est la seule protection réelle — les
 * deux niveaux ne se remplacent pas, le premier évite d'afficher une page vide,
 * le second garde les données.
 *
 * Deux états vivent dans l'URL plutôt que dans du state client :
 *
 *   - les FILTRES (`?q=`, `?role=`, `?actif=`), parce qu'ils sont appliqués par
 *     le serveur : la liste rendue est exactement celle que l'endpoint a
 *     renvoyée, et l'URL dit laquelle.
 *   - le PANNEAU ouvert (`?compte=<id>` pour une fiche, `?nouveau=1` pour une
 *     création), pour la même raison que le dossier d'arbitrage (cf.
 *     `arbitrage/page.tsx`) : la fiche d'un compte se discute, son lien doit
 *     pouvoir se coller dans un message. Le panneau est alors rendu côté
 *     serveur, sans second aller-retour depuis le navigateur, et le retour
 *     arrière le referme.
 */
export default async function AdminPage({
  params,
  searchParams,
}: {
  params: Promise<{ profile: string }>;
  searchParams: Promise<{
    q?: string;
    role?: string;
    actif?: string;
    compte?: string;
    nouveau?: string;
  }>;
}) {
  const [{ profile }, query] = await Promise.all([params, searchParams]);
  if (!PROFILE_KEYS.includes(profile as ProfileKey)) notFound();
  const key = profile as ProfileKey;

  const me = await getMe();
  if (!isAdminRole(me.role)) notFound();

  // Un `?compte=` non numérique (lien tronqué, URL bricolée) ne doit pas partir
  // en requête : il redevient « aucune fiche ouverte ».
  const compte = Number(query.compte);
  const selected = Number.isInteger(compte) && compte > 0 ? compte : undefined;

  return (
    <View>
      <AdminView
        profile={key}
        filters={{
          q: query.q?.trim() || undefined,
          role: query.role || undefined,
          actif: query.actif === "oui" ? true : query.actif === "non" ? false : undefined,
        }}
        selected={selected}
        nouveau={query.nouveau === "1"}
      />
    </View>
  );
}
