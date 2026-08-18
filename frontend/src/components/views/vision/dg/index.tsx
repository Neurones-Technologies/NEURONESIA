import { ReactNode } from "react";
import { DgTableauDeBord } from "./DgTableauDeBord";
import { DgTrajectoire } from "./DgTrajectoire";
import { DgPilotage } from "./DgPilotage";
import { DgFactures } from "./DgFactures";

/** Registre des onglets du cockpit DG : chaque clé est un segment d'URL
 * (`/dg/vision/<clé>`) et doit avoir son entrée dans `VISION_SECTIONS.dg`
 * (cf. lib/data/sections.ts) — sinon le menu affiche un onglet sans page, ou
 * l'inverse. La route valide le segment avant d'appeler ce registre.
 *
 * Issu du découpage de l'ancienne page unique DgVision (mode scroll) : chaque
 * onglet ne paie plus que ses propres appels API au lieu de tous les payer au
 * chargement. « Tableau de bord » reste la première section déclarée : c'est
 * elle qui porte le briefing du jour (cf. defaultVisionSection).
 *
 * Aucun onglet DG ne lit de paramètre d'URL pour l'instant — les pages
 * ignorent simplement `params`, comme le permet le registre mutualisé. */
export const DG_SECTIONS: Record<string, () => ReactNode> = {
  "tableau-de-bord": () => <DgTableauDeBord />,
  trajectoire: () => <DgTrajectoire />,
  pilotage: () => <DgPilotage />,
  factures: () => <DgFactures />,
};
