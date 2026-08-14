import { ReactNode } from "react";
import { ProfileKey } from "@/lib/types";
import { DC_SECTIONS, DcSectionParams } from "./dc";
import { DF_SECTIONS } from "./df";

/** Registres de sections des profils en navigation PAR ROUTE (cf.
 * `VISION_NAV_MODE` dans lib/data/sections.ts).
 *
 * Ce fichier existe pour que `app/[profile]/vision/[section]/page.tsx` n'ait pas à
 * connaître les profils un par un : la route valide le segment contre
 * `VISION_SECTIONS`, puis demande ici quoi rendre. Ajouter un profil en mode
 * route se fait en deux endroits — son menu et ce registre — et le test e2e
 * parcourt les deux pour interdire le menu qui pointe dans le vide.
 *
 * Les paramètres d'URL sont mutualisés : les pages DC portent une cadence de
 * lecture (`?periode=`), un exercice (`?annee=`) et une vue interne (`?vue=`), les
 * onglets DAF seulement un exercice. Une page ignore simplement ce qui ne la
 * concerne pas. */
export type SectionParams = DcSectionParams;

export type SectionRegistry = Record<string, (params: SectionParams) => ReactNode>;

export const SECTION_REGISTRIES: Partial<Record<ProfileKey, SectionRegistry>> = {
  dc: DC_SECTIONS,
  df: DF_SECTIONS,
};
