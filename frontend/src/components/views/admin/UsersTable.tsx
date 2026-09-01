import Link from "next/link";

import type { AdminUser, UsersFilters } from "@/lib/api/admin";
import { ROLE_LABELS, roleToProfile } from "@/lib/auth/roles";
import { formatDate } from "@/lib/format";
import { Tag } from "@/components/ui/primitives";
import { adminHref } from "@/components/views/admin/href";

/** Liste des comptes.
 *
 * Composant serveur : aucune donnée n'est rechargée depuis le navigateur, et
 * l'ouverture d'une fiche est un simple lien (`?compte=<id>`) que le serveur
 * rend.
 *
 * Deux repères mènent à la fiche, un seul est FOCUSABLE. Le nom porte le lien
 * réel ; le bouton « Modifier » de la dernière colonne est un raccourci souris,
 * `tabIndex={-1}` et `aria-hidden`, parce que deux liens vers la même cible
 * feraient dire deux fois la même chose à un lecteur d'écran. Il existe pour une
 * raison précise : sans lui, rien à l'écran ne disait qu'un compte se modifie —
 * un nom souligné se lit comme un détail à consulter, pas comme un geste
 * d'administration, et la liste passait pour un tableau en lecture seule.
 *
 * Trois signaux tenus distincts, parce qu'ils appellent des gestes différents :
 * DÉSACTIVÉ (l'accès a été retiré), JAMAIS CONNECTÉ (l'accès a été ouvert et
 * personne ne s'en est servi) et SANS COCKPIT (le rôle n'a aucun écran — le
 * compte se connecte et n'arrive nulle part, cf. `api/auth/login/route.ts`).
 */
export function UsersTable({
  profile,
  users,
  filters,
  selected,
}: {
  profile: string;
  users: AdminUser[];
  filters: UsersFilters;
  selected?: number;
}) {
  if (users.length === 0) {
    return (
      <p className="arb-empty arb-empty--inline">
        Aucun compte ne correspond à ces filtres.
      </p>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table className="tb">
        <thead>
          <tr>
            <th>Compte</th>
            <th>Rôle</th>
            <th>Statut</th>
            <th>Dernière connexion</th>
            <th>Créé le</th>
            <th className="r">
              <span className="sr-only">Modifier</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => {
            const cockpit = u.role === "admin" ? "admin" : roleToProfile(u.role);
            return (
              <tr key={u.id} aria-current={u.id === selected ? "true" : undefined}>
                <td>
                  <Link className="linkish" href={adminHref(profile, filters, u.id)}>
                    {u.full_name || u.email}
                  </Link>
                  <div className="row-s mono">{u.email}</div>
                </td>
                <td>
                  {ROLE_LABELS[u.role] ?? u.role}
                  {!cockpit && (
                    <div className="row-s">
                      aucun cockpit — ce compte se connecte sans arriver sur un écran
                    </div>
                  )}
                </td>
                <td>
                  {u.is_active ? (
                    <Tag variant="s">actif</Tag>
                  ) : (
                    <Tag variant="r">désactivé</Tag>
                  )}
                </td>
                <td className="mono">
                  {u.last_login ? (
                    formatDate(u.last_login)
                  ) : (
                    <Tag variant="w">jamais</Tag>
                  )}
                </td>
                <td className="mono">{formatDate(u.created_at)}</td>
                <td className="tb-act">
                  <Link
                    className="tb-open"
                    href={adminHref(profile, filters, u.id)}
                    tabIndex={-1}
                    aria-hidden="true"
                  >
                    Modifier
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
