import { ReactNode } from "react";
import { estPeriode, Periode } from "@/lib/api/commercial";
import { DcPipeline } from "./DcPipeline";
import { DcBaseInstallee } from "./DcBaseInstallee";
import { DcMixOffre } from "./DcMixOffre";
import { DcTransformation } from "./DcTransformation";
import { DcObjectifs } from "./DcObjectifs";
import { DcComptes } from "./DcComptes";
import { DcPipeQualite } from "./DcPipeQualite";
import { DcCycleVie } from "./DcCycleVie";
import { DcEquipe } from "./DcEquipe";
import { DcMarche } from "./DcMarche";
import { DcVisites } from "./DcVisites";

/** Paramètres d'URL communs aux onglets DC.
 *
 * La cadence de lecture (§1 du CR : mensuel, trimestriel, annuel) et l'exercice
 * vivent dans la query string plutôt que dans un état client. Les onglets restent
 * donc des composants serveur, et une lecture précise se partage par lien — ce qui
 * compte pour un chiffre commenté en revue de performance. */
export interface DcSectionParams {
  periode?: string;
  annee?: string;
}

function periodeDe(params: DcSectionParams, defaut: Periode): Periode {
  return estPeriode(params.periode) ? params.periode : defaut;
}

function anneeDe(params: DcSectionParams): number | undefined {
  const n = Number(params.annee);
  // Borne basse volontaire : une année aberrante dans l'URL doit retomber sur le
  // défaut serveur (exercice courant), pas produire un écran vide sans explication.
  return Number.isInteger(n) && n >= 2000 && n <= 2100 ? n : undefined;
}

/** Registre des onglets du cockpit DC : chaque clé est un segment d'URL
 * (`/dc/vision/<clé>`) et doit avoir son entrée dans `VISION_SECTIONS.dc`
 * (cf. lib/data/sections.ts) — sinon le menu affiche un onglet sans page, ou
 * l'inverse. La route valide le segment avant d'appeler ce registre.
 *
 * L'ordre suit celui du menu : pilotage du chiffre (pipeline, objectifs), puis
 * animation du portefeuille (comptes, base installée), puis tenue du pipe
 * (à closer, cycle de vie), puis lecture de marché (mix d'offre, secteurs), puis
 * équipe (équipe, transformation), et enfin le terrain (visites). */
export const DC_SECTIONS: Record<string, (params: DcSectionParams) => ReactNode> = {
  pipeline: () => <DcPipeline />,
  objectifs: (p) => <DcObjectifs periode={periodeDe(p, "trimestre")} annee={anneeDe(p)} />,
  comptes: () => <DcComptes />,
  "base-installee": () => <DcBaseInstallee />,
  "pipe-qualite": () => <DcPipeQualite />,
  "cycle-vie": () => <DcCycleVie />,
  "mix-offre": () => <DcMixOffre />,
  marche: () => <DcMarche />,
  equipe: (p) => <DcEquipe periode={periodeDe(p, "mois")} annee={anneeDe(p)} />,
  transformation: () => <DcTransformation />,
  visites: () => <DcVisites />,
};
