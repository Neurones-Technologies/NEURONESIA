import Link from "next/link";

import type { UserDetail, UsersFilters } from "@/lib/api/admin";
import { adminHref } from "@/components/views/admin/href";
import { Modale } from "@/components/views/admin/Modale";
import { UserActions } from "@/components/views/admin/UserActions";

/** Modale de modification d'un compte : les champs, et rien d'autre.
 *
 * Elle a d'abord montré ce que le compte atteint et ce qu'il a produit —
 * périmètre, modules, questions au Copilote, arbitrages, journal. Tout cela est
 * retiré : sur une modale, ces blocs poussaient hors de vue les champs qu'on
 * était venu remplir, et le compte se lit déjà dans la liste. Ce qui reste est
 * le geste.
 *
 * `getUserDetail` continue de servir la fiche, pour deux valeurs qu'aucune autre
 * lecture ne donne : `est_moi` (qui commande le refus d'auto-suppression) et
 * `perimetre.is_admin`. Le reste de ce que l'endpoint calcule n'est plus
 * affiché — un coût serveur sans emploi, à retirer côté backend si la fiche
 * reste ce formulaire.
 */
export function UserModal({
  profile,
  detail,
  filters,
  roles,
  adminsActifs,
}: {
  profile: string;
  detail: UserDetail | null;
  filters: UsersFilters;
  roles: string[];
  adminsActifs: number;
}) {
  const fermer = adminHref(profile, filters, null);

  // Le compte supprimé est le cas NORMAL, pas une panne : l'URL de la fiche
  // survit à la suppression (lien partagé, retour arrière, rechargement).
  if (!detail) {
    return (
      <Modale eyebrow="Modifier le compte" titre="Ce compte n'existe plus" fermer={fermer}>
        <p>La suppression reste inscrite au journal, avec son auteur et sa date.</p>
        <div className="acts">
          <Link className="btn" href={fermer}>
            Revenir à la liste
          </Link>
        </div>
      </Modale>
    );
  }

  const { compte, perimetre } = detail;

  return (
    <Modale
      eyebrow={`Modifier le compte${compte.est_moi ? " · vous" : ""}`}
      titre={compte.full_name || compte.email}
      fermer={fermer}
    >
      <UserActions
        profile={profile}
        compte={compte}
        roles={roles}
        adminsActifs={adminsActifs}
        perimetreAdmin={perimetre.is_admin}
      />
    </Modale>
  );
}
