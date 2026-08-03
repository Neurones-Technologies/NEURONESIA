import type { ArbitrageCandidate, PayeurClasse, PayeurProfile, SignalNature } from "@/lib/api/arbitrage";
import { ROLE_LABELS, roleToProfile } from "@/lib/auth/roles";
import { formatNumber } from "@/lib/format";
import { ProfileKey, Variant } from "@/lib/types";

/** Vocabulaire commun de la vue Arbitrages.
 *
 * Ce module n'a pas de directive : il est importé aussi bien par les Server
 * Components (panneau de dossier) que par les composants client (file de
 * travail, registre). Il ne doit donc jamais toucher au réseau ni aux cookies —
 * uniquement des libellés, des teintes et des calculs purs. */

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? (role || "—");
}

/** Sigle du rôle, pour les endroits où le libellé complet ne tient pas — une
 * ligne de file large de 300 px ne peut pas porter « Direction générale » sans
 * repousser tout le reste. Le libellé entier reste dans la fiche de détail. */
export const ROLE_SHORT: Record<string, string> = {
  admin: "ADM",
  dg: "DG",
  dir_commercial: "DC",
  dir_operations: "DO",
  dir_financier: "DF",
  commercial: "AM",
  presale: "AV",
};

export function roleShort(role: string): string {
  return ROLE_SHORT[role] ?? (role || "—");
}

/** Le `subject_label` du backend tient en une phrase : « CLIENT — 7 facture(s)
 * échue(s) contre cross-sell en cours ». Dans la file, la lire d'un bloc
 * revenait à empiler six lignes de texte par dossier ; le nom du client doit
 * pouvoir être balayé seul, la nature du conflit venir ensuite. */
export function splitSujet(label: string): { client: string; conflit: string } {
  const sep = label.indexOf(" — ");
  if (sep === -1) return { client: label, conflit: "" };
  return { client: label.slice(0, sep), conflit: label.slice(sep + 3) };
}

export function statusVariant(status: string): Variant {
  if (status === "tranchee") return "s";
  if (status === "escaladee") return "r";
  if (status === "reportee" || status === "en_cours") return "w";
  return "n";
}

export const STATUS_LABELS: Record<string, string> = {
  en_cours: "en cours",
  tranchee: "tranchée",
  reportee: "reportée",
  escaladee: "escaladée",
  suspendue: "suspendue",
};

export const VERDICT_LABELS: Record<string, string> = {
  confirme: "confirmée",
  infirme: "infirmée",
  partiel: "partiellement",
};

export const VERDICT_VARIANT: Record<string, Variant> = {
  confirme: "s",
  infirme: "r",
  partiel: "w",
};

export const CONSEQUENCE_LABELS: Record<string, string> = {
  s: "favorable",
  r: "défavorable",
  w: "incertain",
  n: "neutre",
};

/** Un fait lu dans le miroir est fiable, une déduction sur cycle supposé ne l'est
 * pas au même titre — la teinte le dit sans avoir à lire la note de méthode. */
export const NATURE_VARIANT: Record<SignalNature, Variant> = {
  mesuré: "s",
  observé: "n",
  inféré: "w",
};

/** Libellés des classes de payeur — doublon assumé de `payeur.CLASSE_LABELS`
 * côté backend : une décision journalisée conserve la CLASSE brute qui a servi à
 * la prendre (`profil_payeur_classe`), pas son libellé, pour que le registre reste
 * relisible même si la formulation évolue. Il faut donc pouvoir la traduire ici. */
export const PAYEUR_CLASSE_LABELS: Record<string, string> = {
  intragroupe: "entité du groupe",
  amelioration: "paie mieux qu'avant",
  stable_rapide: "payeur rapide et stable",
  stable_lent: "payeur lent mais stable",
  stable: "comportement stable",
  vigilance: "ralentissement modéré",
  degradation: "ralentissement marqué",
  paiements_stoppes: "paiements arrêtés",
  defaillance_probable: "défaillance probable",
  historique_insuffisant: "historique insuffisant",
  non_calcule: "profil non calculé",
};

/** Teinte de la classe de payeur. Le vert n'est pas « bon client » mais « rien
 * dans son comportement de paiement ne justifie de bloquer » — la nuance compte,
 * un client stable peut devoir 3 milliards. */
export const PAYEUR_VARIANT: Record<PayeurClasse, Variant> = {
  paiements_stoppes: "r",
  defaillance_probable: "r",
  degradation: "r",
  vigilance: "w",
  historique_insuffisant: "w",
  stable: "n",
  stable_lent: "s",
  stable_rapide: "s",
  amelioration: "s",
  intragroupe: "n",
  non_calcule: "n",
};

/** Ce que la classe implique comme conduite, en une ligne — la traduction du
 * constat en langage de décision, sans reprendre la recommandation d'option. */
export const PAYEUR_PORTEE: Record<PayeurClasse, string> = {
  paiements_stoppes: "le client s'est arrêté de payer : appeler avant de décider",
  defaillance_probable: "aucun encaissement jamais constaté",
  degradation: "ralentissement réel — c'est le cas où bloquer se justifie",
  vigilance: "à signaler, pas encore à sanctionner",
  historique_insuffisant: "trop peu de paiements pour conclure",
  stable: "rien de nouveau côté risque client",
  stable_lent: "retard structurel, pas une défaillance",
  stable_rapide: "probable incident de facturation",
  amelioration: "dynamique favorable, un blocage la casserait",
  intragroupe: "compte courant du groupe, pas un impayé client",
  non_calcule: "calcul absent — dossier instruit sur le seul impayé",
};

export const ACTIF_LABELS: Record<string, string> = {
  oui: "dossier commercial toujours d'actualité",
  non: "dossier commercial abandonné côté client",
  incertain: "actualité du dossier incertaine",
};

export function prioriteVariant(niveau: number): Variant {
  if (niveau >= 3) return "r";
  if (niveau === 2) return "w";
  if (niveau === 1) return "n";
  return "s";
}

/** Le champ `echeance` d'un candidat vaut toujours la chaîne littérale "aucune"
 * côté backend (aucune échéance contractuelle exploitable dans le miroir) — ce
 * n'est pas une date, jamais la passer à `formatDate`. */
export function echeanceLabel(echeance: string, formatDate: (iso: string) => string): string {
  if (!echeance || echeance === "aucune") return "aucune échéance contractuelle dans le miroir";
  return formatDate(echeance);
}

export interface PayeurTrajectoire {
  /** `tendance` : même mesure à deux moments, la flèche est légitime.
   *  `silence` : il n'y a pas de trajectoire, il y a une absence.
   *  `inconnu` : les fenêtres sont trop pauvres pour mesurer quoi que ce soit. */
  mode: "tendance" | "silence" | "inconnu";
  /** Ce que mesure le grand chiffre. Sans lui, « 781 j » est un nombre nu. */
  label: string;
  valeur: string;
  /** Même mesure, une fenêtre plus tôt — jamais renseigné hors mode `tendance`. */
  avant: string | null;
  /** Fait secondaire, en toutes lettres : le rythme d'avant, ou l'absence de mesure. */
  rappel: string | null;
}

/** Ce que le grand chiffre du bandeau de paiement doit dire.
 *
 * Trois situations, et surtout PAS une seule forme pour les trois. La flèche
 * `14 j → 36 j` compare une même grandeur à deux moments : elle est juste. La
 * même flèche appliquée à un client qui a cessé de payer donnait
 * `244 j → 781 j`, où 244 j est un délai moyen de règlement et 781 j un nombre
 * de jours de silence — deux grandeurs incommensurables reliées par un signe qui
 * affirme une continuité inexistante. Un client qui s'est arrêté n'a pas de
 * trajectoire : il a une absence, et c'est l'absence qu'on montre, avec son
 * rythme passé rappelé à part plutôt que mis en regard. */
export function payeurTrajectoire(p: PayeurProfile): PayeurTrajectoire {
  if (p.classe === "paiements_stoppes" || p.nb_paiements_recents === 0) {
    return {
      mode: "silence",
      label: "sans aucun encaissement depuis",
      valeur: p.jours_depuis_dernier_paiement !== null ? `${formatNumber(p.jours_depuis_dernier_paiement)} j` : "—",
      avant: null,
      rappel:
        p.delai_ancien_jours !== null
          ? `réglait auparavant en ${formatNumber(p.delai_ancien_jours)} j en moyenne`
          : null,
    };
  }
  if (p.delai_recent_jours === null) {
    return {
      mode: "inconnu",
      label: "délai de règlement",
      valeur: "—",
      avant: null,
      rappel: "non mesurable sur la fenêtre observée",
    };
  }
  return {
    mode: "tendance",
    label: p.delai_ancien_jours !== null ? "délai de règlement, avant → maintenant" : "délai de règlement récent",
    valeur: `${formatNumber(p.delai_recent_jours)} j`,
    avant: p.delai_ancien_jours !== null ? `${formatNumber(p.delai_ancien_jours)} j` : null,
    rappel: null,
  };
}

/** Trajectoire compacte pour une ligne de liste : `36 j → 92 j`. */
export function trajectoireCourte(p: PayeurProfile): string {
  if (p.delai_recent_jours !== null) {
    return p.delai_ancien_jours !== null
      ? `${formatNumber(p.delai_ancien_jours)} j → ${formatNumber(p.delai_recent_jours)} j`
      : `${formatNumber(p.delai_recent_jours)} j`;
  }
  if (p.jours_depuis_dernier_paiement !== null) {
    return `aucun paiement depuis ${formatNumber(p.jours_depuis_dernier_paiement)} j`;
  }
  return "délai non mesurable";
}

/** Comment lire le signal commercial retenu : son type, sa nature, et le fait
 * qu'il a été choisi sur le montant le plus élevé quand le client en portait
 * plusieurs — un critère de tri, pas un jugement d'urgence. */
export function signalSummary(c: ArbitrageCandidate): string {
  const parts = [`${c.signal_type} (${c.signal_nature})`];
  if (c.signaux_commerciaux_nb > 1) {
    parts.push(`retenu comme le plus gros montant parmi ${formatNumber(c.signaux_commerciaux_nb)} signaux du client`);
  }
  if (c.signal_age_mois !== null && c.signal_cycle_mois) {
    const reste = c.signal_cycle_mois - c.signal_age_mois;
    parts.push(
      reste > 0
        ? `dernier achat il y a ${formatNumber(c.signal_age_mois)} mois, cycle supposé de ${formatNumber(c.signal_cycle_mois)} mois → fenêtre estimée dans ~${formatNumber(reste)} mois`
        : `dernier achat il y a ${formatNumber(c.signal_age_mois)} mois, cycle supposé de ${formatNumber(c.signal_cycle_mois)} mois déjà dépassé`
    );
  } else if (c.signal_age_mois !== null) {
    parts.push(`dernier achat il y a ${formatNumber(c.signal_age_mois)} mois`);
  }
  return parts.join(" · ");
}

/** Profils concernés par un dossier : celui qui a mandat + ceux dont la position
 * est citée. Une ligne sans aucun rôle rattaché (décision antérieure à ce module,
 * ex. un GO/NO-BID d'avant-vente) n'est dans le périmètre de personne — elle
 * n'apparaît qu'en « Tous les dossiers », plutôt que d'être présentée à chacun
 * comme si elle le concernait. */
export function concernedProfiles(mandatRole: string, profilsImpliques: string[]): ProfileKey[] {
  return [mandatRole, ...profilsImpliques]
    .map((r) => roleToProfile(r))
    .filter((p): p is ProfileKey => p !== null);
}

export function isRowRelevant(
  profile: ProfileKey,
  isAdmin: boolean,
  mandatRole: string,
  profilsImpliques: string[]
): boolean {
  if (isAdmin) return true;
  return concernedProfiles(mandatRole, profilsImpliques).includes(profile);
}

/** Jours restants avant une échéance de relecture — négatif si dépassée.
 * `null` quand la décision n'a pas de date (antérieure à ce module). */
export function joursAvant(iso: string | null): number | null {
  if (!iso) return null;
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target - today.getTime()) / 86_400_000);
}
