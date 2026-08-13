import { ReactNode } from "react";
import { estPeriode, Periode } from "@/lib/api/commercial";
import { DcPipeline } from "./DcPipeline";
import { DcBaseInstallee } from "./DcBaseInstallee";
import { DcMixOffre } from "./DcMixOffre";
import { DcTransformation } from "./DcTransformation";
import { DcObjectifs } from "./DcObjectifs";
import { DcComptes } from "./DcComptes";
import { DcPics } from "./DcPics";
import { DcPipeQualite } from "./DcPipeQualite";
import { DcCycleVie } from "./DcCycleVie";
import { DcEfficacite } from "./DcEfficacite";
import { DcProspection } from "./DcProspection";
import { DcMarche } from "./DcMarche";
import { DcSecteurs } from "./DcSecteurs";
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
 * l'inverse. La route valide le segment avant d'appeler ce registre, et un test
 * e2e parcourt les deux listes.
 *
 * L'ordre et le regroupement suivent les six chapitres du compte-rendu d'entretien
 * du 04/08/2026 : le DC doit reconnaître SA demande dans le menu. Chaque écran
 * reste une page distincte, pour ne payer que ses propres appels. */
export const DC_SECTIONS: Record<string, (params: DcSectionParams) => ReactNode> = {
  // 1. Pilotage stratégique du portefeuille
  marche: () => <DcMarche />,
  "base-installee": () => <DcBaseInstallee />,
  pics: () => <DcPics />,
  // 2. Suivi commercial par compte
  comptes: () => <DcComptes />,
  "cycle-vie": () => <DcCycleVie />,
  // 3. Prospection et performance commerciale
  efficacite: (p) => <DcEfficacite periode={periodeDe(p, "mois")} annee={anneeDe(p)} />,
  prospection: (p) => <DcProspection periode={periodeDe(p, "mois")} annee={anneeDe(p)} />,
  // 4. Analyse sectorielle et pipeline
  secteurs: () => <DcSecteurs />,
  pipeline: () => <DcPipeline />,
  "pipe-qualite": () => <DcPipeQualite />,
  objectifs: (p) => <DcObjectifs periode={periodeDe(p, "trimestre")} annee={anneeDe(p)} />,
  "mix-offre": () => <DcMixOffre />,
  // 5. Aide à la décision
  transformation: () => <DcTransformation />,
  // 6. Traçabilité terrain
  visites: () => <DcVisites />,
};
