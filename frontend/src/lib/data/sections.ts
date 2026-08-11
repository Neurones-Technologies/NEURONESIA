import { ProfileKey } from "@/lib/types";

export interface SectionNavItem {
  id: string;
  label: string;
}

/** Découpage en sections de la vue Cockpit, par profil. Défini ici (et non dans
 * la vue) pour être importable depuis l'en-tête, qui est un composant client.
 *
 * Deux modes de navigation cohabitent, selon `VISION_NAV_MODE` :
 *
 * - `"scroll"` (DG) : une seule page, les `id` correspondent aux `<Section id=…>`
 *   de la vue et le menu fait son scroll-spy dessus. L'ordre du menu doit alors
 *   suivre l'ordre du document, sinon le surlignage saute.
 * - `"route"` (DC) : une page par section, les `id` sont des segments d'URL
 *   (`/dc/vision/pipeline`). Le menu rend des liens ; l'ordre est libre. Chaque
 *   `id` doit avoir son entrée dans le registre de la vue (cf.
 *   components/views/vision/dc/index.tsx). */
export const VISION_SECTIONS: Partial<Record<ProfileKey, readonly SectionNavItem[]>> = {
  dg: [
    { id: "tableau-de-bord", label: "Tableau de bord" },
    { id: "trajectoire", label: "Trajectoire financière" },
    { id: "risques", label: "Dépendances et risques" },
  ],
  dc: [
    { id: "pipeline", label: "Pipeline et forecast" },
    { id: "base-installee", label: "Base installée" },
    { id: "mix-offre", label: "Mix d'offre" },
    { id: "transformation", label: "Transformation" },
  ],
};

export type VisionNavMode = "scroll" | "route";

/** Mode de navigation du menu de sections, par profil. Un profil absent est en
 * `"scroll"` — le comportement historique. */
export const VISION_NAV_MODE: Partial<Record<ProfileKey, VisionNavMode>> = {
  dc: "route",
};

export function visionNavMode(profile: ProfileKey): VisionNavMode {
  return VISION_NAV_MODE[profile] ?? "scroll";
}

/** Section par défaut d'un profil en mode `"route"` — cible de la redirection
 * depuis `/{profile}/vision`. */
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
