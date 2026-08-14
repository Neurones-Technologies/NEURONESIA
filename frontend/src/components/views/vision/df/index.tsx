import { ReactNode } from "react";
import { DfVision } from "../DfVision";
import { DfBudget } from "./DfBudget";
import { DfRelationCommerciale } from "./DfRelationCommerciale";
import { DfTresorerie } from "./DfTresorerie";

/** Paramètres d'URL des onglets DAF.
 *
 * Seul l'exercice est porté ici : les tableaux de bord financiers se lisent par
 * exercice comptable, pas à une cadence libre. Le paramètre vit dans la query
 * string plutôt que dans un état client, pour la même raison que côté DC — les
 * onglets restent des composants serveur, et une lecture commentée en comité se
 * partage par lien. */
export interface DfSectionParams {
  annee?: string;
}

function anneeDe(params: DfSectionParams): number | undefined {
  const n = Number(params.annee);
  // Une année aberrante dans l'URL retombe sur le défaut serveur (exercice
  // courant) plutôt que de produire un écran vide sans explication.
  return Number.isInteger(n) && n >= 2000 && n <= 2100 ? n : undefined;
}

/** Registre des onglets du cockpit DAF : chaque clé est un segment d'URL
 * (`/df/vision/<clé>`) et doit avoir son entrée dans `VISION_SECTIONS.df`
 * (cf. lib/data/sections.ts) — sinon le menu affiche un onglet sans page, ou
 * l'inverse. La route valide le segment avant d'appeler ce registre.
 *
 * L'ordre suit celui du menu et celui de la note du DAF : l'écran financier
 * historique (encours et marge, avec le briefing et les narrations IA), puis les
 * trois tableaux de bord demandés — budget, relation commerciale, trésorerie
 * prévisionnelle. */
export const DF_SECTIONS: Record<string, (params: DfSectionParams) => ReactNode> = {
  encours: () => <DfVision />,
  budget: (p) => <DfBudget annee={anneeDe(p)} />,
  "relation-commerciale": (p) => <DfRelationCommerciale annee={anneeDe(p)} />,
  tresorerie: (p) => <DfTresorerie annee={anneeDe(p)} />,
};
