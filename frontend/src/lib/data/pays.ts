/** Périmètre géographique du cockpit DG.
 *
 * Le groupe opère sur trois entités — Côte d'Ivoire, Burkina Faso, Guinée —,
 * que nt360 distingue (`?entite=CI|BF|GN`). Le sélecteur ventile le BRIEFING
 * DG : chaque pays a le sien, calculé sur les seules données de l'entité
 * (cf. backend modules/uc_briefing/facts._DG_PAR_ENTITE). Les tuiles et les
 * autres onglets restent au niveau groupe et le disent (`PerimetreGroupe`) :
 * leurs sources ne sont pas encore ventilées par entité.
 *
 * Le pays vit dans l'URL (`?pays=…`) comme la cadence et l'exercice : pages en
 * composants serveur, lecture partageable par lien. */

export type Pays = "ci" | "bf" | "gn";

export const PAYS: { id: Pays; label: string }[] = [
  { id: "ci", label: "Côte d'Ivoire" },
  { id: "bf", label: "Burkina Faso" },
  { id: "gn", label: "Guinée" },
];

/** Pays affiché quand l'URL n'en porte pas : la Côte d'Ivoire, entité
 * principale du groupe. Il n'est pas écrit dans l'URL (cf. PaysNav). */
export const PAYS_PAR_DEFAUT: Pays = "ci";

export function estPays(valeur: string | undefined): valeur is Pays {
  return PAYS.some((p) => p.id === valeur);
}

/** Un `?pays=` absent ou absurde retombe sur le pays par défaut : un lien mal
 * recopié ouvre le cockpit habituel, pas un écran d'erreur. */
export function paysDe(valeur: string | undefined): Pays {
  return estPays(valeur) ? valeur : PAYS_PAR_DEFAUT;
}

export function paysLabel(pays: Pays): string {
  return PAYS.find((p) => p.id === pays)?.label ?? pays;
}

// ── Pays d'un COMPTE (écran d'administration) ────────────────────────────────
// Codes du serveur (users.pays) : "" = groupe, CI / BF / GN = périmètre imposé
// à toutes les pages du compte. Distincts des identifiants d'URL ci-dessus
// (minuscules), qui ne servent qu'au sélecteur.

export const PAYS_COMPTE: { code: string; label: string }[] = [
  { code: "", label: "Groupe (tous pays)" },
  { code: "CI", label: "Côte d'Ivoire" },
  { code: "BF", label: "Burkina Faso" },
  { code: "GN", label: "Guinée" },
];

/** Rôles toujours rattachés au groupe : le DG pilote les trois entités, l'admin
 * administre tout. Le serveur refuse un pays sur ces comptes. */
export const ROLES_TOUJOURS_GROUPE = ["dg", "admin"];

export function libellePaysCompte(code: string | null | undefined): string {
  return PAYS_COMPTE.find((p) => p.code === (code ?? "").toUpperCase())?.label ?? "Groupe (tous pays)";
}
