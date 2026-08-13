import { ProfileKey } from "@/lib/types";

/** Vue interne d'une section — niveau d'onglet DANS une page.
 *
 * Sert à regrouper plusieurs écrans sur une même page sans rien retirer : chaque
 * vue garde son contenu intégral, et l'URL la désigne par `?vue=`. */
export interface SectionVue {
  id: string;
  label: string;
}

export interface SectionNavItem {
  id: string;
  label: string;
  /** Chapitre auquel la section se rattache, en navigation à deux niveaux.
   * Absent : le profil garde un menu à un seul niveau. */
  group?: string;
  /** Vues internes, quand la page en regroupe plusieurs. La première est celle
   * qu'on obtient sans `?vue=`. Une section sans `vues` reste un écran simple. */
  vues?: readonly SectionVue[];
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
 * Vide aujourd'hui : le DC en avait six, pour ranger quatorze sections que la
 * rangée de menu ne pouvait pas porter. Ses sections ont été regroupées en sept
 * pages à onglets internes (cf. `VISION_SECTIONS.dc`), qui tiennent sur une
 * rangée — le second niveau de menu n'a plus d'objet, et les chapitres du
 * compte-rendu se lisent maintenant dans les onglets de chaque page.
 *
 * Le mécanisme reste en place : un profil qui déclarerait des chapitres ici
 * retrouverait le menu à deux niveaux (cf. shell/Header.tsx). */
export const VISION_GROUPS: Partial<Record<ProfileKey, readonly SectionGroup[]>> = {};

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
  // relation commerciale, trésorerie prévisionnelle) et un volet transverse
  // (formation). L'onglet « Encours et marge » est l'écran financier historique,
  // conservé en tête : il porte le briefing du jour et les narrations IA, que les
  // trois tableaux de bord de la note ne remplacent pas.
  //
  // Le volet « Formation et qualité » est RETIRÉ du menu. La navigation DAF est en
  // mode route et la page valide son segment contre cette liste : retirer l'entrée
  // ici met aussi `/df/vision/formation` en 404, l'onglet n'est donc pas seulement
  // masqué à l'œil, il n'est plus atteignable par URL directe. L'écran lui-même est
  // conservé (components/views/vision/df/DfFormation.tsx, `getFormation` dans
  // lib/api/daf.ts) : le rétablir tient en une ligne ici et une dans DF_SECTIONS.
  df: [
    { id: "encours", label: "Encours et marge" },
    { id: "budget", label: "Budget" },
    { id: "relation-commerciale", label: "Relation commerciale" },
    { id: "tresorerie", label: "Trésorerie prévisionnelle" },
  ],
  // Cockpit DC — six entrées de menu pour sept pages servies (« Mix d'offre » est
  // commentée plus bas, sans être supprimée). Les libellés de vue reprennent la
  // formulation du compte-rendu du 04/08/2026 (« Indice de prospection », « À
  // closer / à compléter », « Écart vendu / objectif ») : le DC doit reconnaître
  // SA demande, pas déduire à quel besoin répond un onglet nommé autrement.
  //
  // Le découpage précédent donnait une page par vue, soit quatorze entrées de
  // menu sur deux niveaux. Trois raisons de les regrouper :
  //
  // - Quatorze entrées ne débordaient pas seulement d'une rangée : elles
  //   imposaient un menu à deux étages, et forçaient à couper le prefetch
  //   (Header.tsx : onze liens visibles × 0,6 à 1,6 s de rendu serveur). Sept
  //   entrées tiennent sur une rangée et rendent le préchargement finançable.
  // - Le découpage se calquait sur les chapitres du compte-rendu, c'est-à-dire
  //   sur un ordre d'entretien, pas sur des tâches. « Pics », « Comptes » et
  //   « Prospection » étaient trois pages qui découpaient un même appel
  //   (`getComptesDc`) ; regroupées, elles le partagent.
  // - Aucun contenu n'est retiré : les quatorze vues gardent leurs blocs, leurs
  //   chiffres et leurs notes. Elles changent de point de montage, pas de fond.
  //
  // L'ordre des vues dans une page suit celui du compte-rendu. L'ordre des PAGES,
  // lui, place « Marché » en tête : c'est la page d'ouverture du cockpit DC (cf.
  // `defaultVisionSection`), la lecture du marché venant avant celle du
  // portefeuille et du pipeline qu'elle sert à cadrer.
  dc: [
    {
      id: "marche",
      label: "Marché",
      vues: [
        { id: "marche", label: "Tendances et marché" },
        { id: "secteurs", label: "Tendance des secteurs" },
      ],
    },
    {
      id: "portefeuille",
      label: "Portefeuille",
      vues: [
        { id: "comptes", label: "Comptes par ventes" },
        { id: "pics", label: "Pics et alertes" },
        { id: "base-installee", label: "Animation de compte" },
      ],
    },
    {
      id: "pipeline",
      label: "Pipeline",
      vues: [
        { id: "pipeline", label: "Pipeline et forecast" },
        { id: "pipe-qualite", label: "À closer / à compléter" },
        { id: "cycle-vie", label: "Cycle de vie ≥ 30 M" },
      ],
    },
    {
      id: "objectifs",
      label: "Objectifs et performance",
      vues: [
        { id: "objectifs", label: "Écart vendu / objectif" },
        { id: "efficacite", label: "Indice d'efficacité" },
        { id: "prospection", label: "Indice de prospection" },
      ],
    },
    // Mix d'offre : entrée retirée du menu, ses deux tuiles ayant été repliées
    // dans « Diagnostic » (cf. dc/DcTransformation.tsx). La page reste servie à
    // son URL — `/dc/vision/mix-offre` est encore déclarée dans DC_SECTIONS, donc
    // les liens déjà partagés ne tombent pas en 404. Rétablir cette ligne suffit
    // à la faire réapparaître dans le menu.
    // { id: "mix-offre", label: "Mix d'offre" },
    { id: "transformation", label: "Diagnostic" },
    { id: "visites", label: "Fichier de visite" },
  ],
};

/** Anciennes URL de section DC → page qui porte désormais leur contenu.
 *
 * Les quatorze sections d'origine avaient chacune leur URL. Elles ont circulé en
 * lien (revues de performance, messages) et ne doivent pas tomber en 404 : la
 * route les redirige vers `/dc/vision/<page>?vue=<ancien-id>`, qui affiche
 * exactement le même écran.
 *
 * Les clés qui sont AUSSI des identifiants de page (`marche`, `pipeline`,
 * `objectifs`, `mix-offre`, `transformation`, `visites`) n'ont pas à figurer ici :
 * leur URL reste valide telle quelle et ouvre la page sur sa première vue. */
export const ANCIENNES_SECTIONS_DC: Readonly<Record<string, string>> = {
  comptes: "portefeuille",
  pics: "portefeuille",
  "base-installee": "portefeuille",
  "pipe-qualite": "pipeline",
  "cycle-vie": "pipeline",
  efficacite: "objectifs",
  prospection: "objectifs",
  secteurs: "marche",
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

/** Vues internes d'une section, ou tableau vide si elle n'en a pas. */
export function vuesOfSection(profile: ProfileKey, section: string): readonly SectionVue[] {
  return (VISION_SECTIONS[profile] ?? []).find((s) => s.id === section)?.vues ?? [];
}

/** Vue à afficher pour une section, `?vue=` éventuel pris en compte.
 *
 * Retombe sur la première vue déclarée : une valeur inconnue dans l'URL ne doit
 * pas produire une page vide. `undefined` pour une section sans vues. */
export function vueRetenue(
  profile: ProfileKey,
  section: string,
  demandee: string | undefined,
): string | undefined {
  const vues = vuesOfSection(profile, section);
  if (vues.length === 0) return undefined;
  return vues.some((v) => v.id === demandee) ? demandee : vues[0].id;
}
