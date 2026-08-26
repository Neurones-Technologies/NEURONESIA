import type { UsersFilters } from "@/lib/api/admin";

/** URLs de l'écran Comptes, filtres compris.
 *
 * Les liens de la liste doivent CONSERVER les filtres en cours : ouvrir un
 * panneau depuis une recherche puis le fermer devait ramener à cette recherche,
 * pas à la liste entière. Comme les filtres vivent dans l'URL (le serveur les
 * applique), les reconduire ici est la seule façon de ne pas les perdre au clic.
 */
function base(filters: UsersFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.role) params.set("role", filters.role);
  if (filters.actif !== undefined) params.set("actif", filters.actif ? "oui" : "non");
  return params;
}

function href(profile: string, params: URLSearchParams): string {
  const query = params.toString();
  return `/${profile}/admin${query ? `?${query}` : ""}`;
}

/** Fiche d'un compte. `compte` à `null` retire le paramètre : c'est le lien de
 * fermeture, commun aux deux panneaux. */
export function adminHref(
  profile: string,
  filters: UsersFilters,
  compte?: number | null
): string {
  const params = base(filters);
  if (compte) params.set("compte", String(compte));
  return href(profile, params);
}

/** Création d'un compte. Un paramètre distinct de `compte` plutôt qu'un
 * `compte=nouveau` : les deux panneaux n'ont ni le même contenu ni la même
 * lecture serveur, et un identifiant qui n'en est pas un obligerait chaque
 * lecture à s'en défendre. */
export function adminNouveauHref(profile: string, filters: UsersFilters): string {
  const params = base(filters);
  params.set("nouveau", "1");
  return href(profile, params);
}
