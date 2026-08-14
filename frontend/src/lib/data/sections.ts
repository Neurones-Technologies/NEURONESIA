import { ProfileKey } from "@/lib/types";

export interface SectionNavItem {
  id: string;
  label: string;
  /** Chapitre auquel la section se rattache, en navigation à deux niveaux.
   * Absent : le profil garde un menu à un seul niveau. */
  group?: string;
}

/** Chapitre de menu — niveau 1 d'un profil en navigation à deux niveaux. */
export interface SectionGroup {
  id: string;
  /** Libellé affiché, nécessairement court : six chapitres doivent tenir sur une
   * ligne à côté de la puce de profil. */
  label: string;
  /** Intitulé complet, en infobulle. C'est lui qui porte la formulation exacte du
   * document de référence, que le libellé court ne peut pas contenir. */
  title?: string;
}

/** Chapitres du menu, par profil. Leur ordre est celui du menu.
 *
 * Pour le DC, les six chapitres sont ceux du compte-rendu d'entretien du
 * 04/08/2026, dans son ordre : le cockpit doit se lire avec le document sur la
 * table, sans avoir à traduire un intitulé en fonctionnalité.
 *
 * Un profil absent d'ici reste à un seul niveau (cas du DAF, dont les cinq
 * onglets tiennent sans regroupement). */
export const VISION_GROUPS: Partial<Record<ProfileKey, readonly SectionGroup[]>> = {
  dc: [
    { id: "pilotage", label: "Pilotage stratégique", title: "1. Pilotage stratégique du portefeuille" },
    { id: "suivi-compte", label: "Suivi par compte", title: "2. Suivi commercial par compte" },
    { id: "prospection", label: "Prospection et performance", title: "3. Prospection et performance commerciale" },
    { id: "pipeline", label: "Secteurs et pipeline", title: "4. Analyse sectorielle et pipeline" },
    { id: "decision", label: "Aide à la décision", title: "5. Aide à la décision" },
    { id: "terrain", label: "Traçabilité terrain", title: "6. Traçabilité terrain" },
  ],
};

/** Découpage en sections de la vue Cockpit, par profil. Défini ici (et non dans
 * la vue) pour être importable depuis l'en-tête, qui est un composant client.
 *
 * Deux modes de navigation cohabitent, selon `VISION_NAV_MODE` :
 *
 * - `"scroll"` (DG) : une seule page, les `id` correspondent aux `<Section id=…>`
 *   de la vue et le menu fait son scroll-spy dessus. L'ordre du menu doit alors
 *   suivre l'ordre du document, sinon le surlignage saute.
 * - `"route"` (DC, DF) : une page par section, les `id` sont des segments d'URL
 *   (`/dc/vision/pipeline`). Le menu rend des liens ; l'ordre est libre. Chaque
 *   `id` doit avoir son entrée dans le registre de son profil (cf.
 *   components/views/vision/registry.ts). */
export const VISION_SECTIONS: Partial<Record<ProfileKey, readonly SectionNavItem[]>> = {
  dg: [
    { id: "tableau-de-bord", label: "Tableau de bord" },
    { id: "trajectoire", label: "Trajectoire financière" },
    { id: "risques", label: "Dépendances et risques" },
  ],
  // Note « Point DAF financier » du 04/08/2026 : trois tableaux de bord (budget,
  // relation commerciale, trésorerie prévisionnelle). L'onglet « Encours et marge »
  // est l'écran financier historique, conservé en tête : il porte le briefing du
  // jour et les narrations IA, que les trois tableaux de bord de la note ne
  // remplacent pas.
  df: [
    { id: "encours", label: "Encours et marge" },
    { id: "budget", label: "Budget" },
    { id: "relation-commerciale", label: "Relation commerciale" },
    { id: "tresorerie", label: "Trésorerie prévisionnelle" },
  ],
  // Cockpit DC : les sections suivent les six chapitres du compte-rendu du
  // 04/08/2026 (cf. `VISION_GROUPS`), et leurs libellés reprennent la formulation
  // du document — « Indice de prospection », « À closer / à compléter », « Écart
  // vendu / objectif ». Le DC doit reconnaître SA demande dans le menu, pas
  // déduire à quel besoin répond un onglet nommé autrement.
  //
  // Le découpage est plus fin que les chapitres parce qu'il est aussi un découpage
  // de CHARGE : une section = une page = ses propres appels. Regrouper « Pilotage
  // stratégique » sur un seul écran cumulerait quatre appels et recalculerait le
  // marché, servi aussi au chapitre 4.
  //
  // L'ordre à l'intérieur d'un chapitre suit celui du compte-rendu.
  dc: [
    // 1. Pilotage stratégique du portefeuille
    { id: "marche", label: "Tendances et marché", group: "pilotage" },
    { id: "base-installee", label: "Animation de compte", group: "pilotage" },
    { id: "pics", label: "Pics et alertes", group: "pilotage" },
    // 2. Suivi commercial par compte
    { id: "comptes", label: "Comptes par ventes", group: "suivi-compte" },
    { id: "cycle-vie", label: "Cycle de vie ≥ 30 M", group: "suivi-compte" },
    // 3. Prospection et performance commerciale
    { id: "efficacite", label: "Indice d'efficacité", group: "prospection" },
    { id: "prospection", label: "Indice de prospection", group: "prospection" },
    // 4. Analyse sectorielle et pipeline
    { id: "secteurs", label: "Tendance des secteurs", group: "pipeline" },
    { id: "pipeline", label: "Pipeline et forecast", group: "pipeline" },
    { id: "pipe-qualite", label: "À closer / à compléter", group: "pipeline" },
    { id: "objectifs", label: "Écart vendu / objectif", group: "pipeline" },
    { id: "mix-offre", label: "Mix d'offre", group: "pipeline" },
    // 5. Aide à la décision
    { id: "transformation", label: "Diagnostic et recommandations", group: "decision" },
    // 6. Traçabilité terrain
    { id: "visites", label: "Fichier de visite", group: "terrain" },
  ],
};

/** Chapitres d'un profil, ou `undefined` s'il est à un seul niveau. */
export function visionGroups(profile: ProfileKey): readonly SectionGroup[] | undefined {
  return VISION_GROUPS[profile];
}

/** Sections d'un chapitre, dans l'ordre du menu. */
export function sectionsOfGroup(profile: ProfileKey, group: string): readonly SectionNavItem[] {
  return (VISION_SECTIONS[profile] ?? []).filter((s) => s.group === group);
}

/** Chapitre auquel appartient une section. `undefined` si la section est inconnue
 * ou si le profil n'a pas de chapitres. */
export function groupOfSection(profile: ProfileKey, section: string | undefined): string | undefined {
  if (!section) return undefined;
  return (VISION_SECTIONS[profile] ?? []).find((s) => s.id === section)?.group;
}

/** Première section d'un chapitre — cible d'un clic sur le chapitre lui-même. */
export function firstSectionOfGroup(profile: ProfileKey, group: string): string | undefined {
  return sectionsOfGroup(profile, group)[0]?.id;
}

export type VisionNavMode = "scroll" | "route";

/** Mode de navigation du menu de sections, par profil. Un profil absent est en
 * `"scroll"` — le comportement historique. */
export const VISION_NAV_MODE: Partial<Record<ProfileKey, VisionNavMode>> = {
  dc: "route",
  df: "route",
};

export function visionNavMode(profile: ProfileKey): VisionNavMode {
  return VISION_NAV_MODE[profile] ?? "scroll";
}

/** Section par défaut d'un profil en mode `"route"` — cible de la redirection
 * depuis `/{profile}/vision`.
 *
 * C'est la PREMIÈRE section déclarée, donc le premier onglet du premier chapitre.
 * Conséquence à connaître avant de réordonner la liste : cette section est l'écran
 * d'ouverture du cockpit, et c'est elle qui doit porter le briefing du jour. */
export function defaultVisionSection(profile: ProfileKey): string | undefined {
  return VISION_SECTIONS[profile]?.[0]?.id;
}

/** URL d'entrée du Cockpit, redirection déjà résolue.
 *
 * En mode `"route"`, `/{profile}/vision` n'est pas une page : elle ne renvoie
 * qu'un `NEXT_REDIRECT` vers la première section (cf. vision/page.tsx). Un lien
 * pointé dessus est donc impossible à précharger utilement — le prefetch met en
 * cache l'ordre de redirection, pas le contenu, et le clic paie quand même le
 * rendu de la cible. Viser directement la section évite ce détour.
 *
 * La redirection reste en place : elle sert les URL tapées à la main et les
 * liens déjà partagés. */
export function visionEntryPath(profile: ProfileKey): string {
  const base = `/${profile}/vision`;
  if (visionNavMode(profile) !== "route") return base;
  const first = defaultVisionSection(profile);
  return first ? `${base}/${first}` : base;
}

export function isVisionSection(profile: ProfileKey, section: string): boolean {
  return (VISION_SECTIONS[profile] ?? []).some((s) => s.id === section);
}
