import { ReactNode } from "react";
import { paysDe, PAYS_AVEC_DONNEES } from "@/lib/data/pays";
import { PaysIndisponible, PaysNav } from "../pays-nav";
import { DgTableauDeBord } from "./DgTableauDeBord";
import { DgTrajectoire } from "./DgTrajectoire";
import { DgPilotage } from "./DgPilotage";
import { DgFactures } from "./DgFactures";
import type { DcSectionParams } from "../dc";

/** Habille chaque onglet DG du sélecteur de pays (à l'extrémité droite de la
 * ligne d'en-tête), et bascule sur l'écran « Donnée non disponible » quand le
 * pays sélectionné n'est pas encore raccordé au miroir. Le pays vit dans l'URL
 * (`?pays=`, cf. lib/data/pays.ts) comme les autres filtres du produit : les
 * onglets restent des composants serveur. */
function page(section: string, rendre: () => ReactNode) {
  return function rendu(params: DcSectionParams): ReactNode {
    const pays = paysDe(params.pays);
    return (
      <>
        <div className="dc-nav-row">
          <PaysNav basePath={`/dg/vision/${section}`} pays={pays} />
        </div>
        {pays !== PAYS_AVEC_DONNEES ? <PaysIndisponible pays={pays} /> : rendre()}
      </>
    );
  };
}

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
 * Seul paramètre d'URL lu par les onglets DG : le pays (`?pays=`), via le
 * wrapper `page` — les vues elles-mêmes ignorent `params`, comme le permet le
 * registre mutualisé. */
export const DG_SECTIONS: Record<string, (params: DcSectionParams) => ReactNode> = {
  "tableau-de-bord": page("tableau-de-bord", () => <DgTableauDeBord />),
  trajectoire: page("trajectoire", () => <DgTrajectoire />),
  pilotage: page("pilotage", () => <DgPilotage />),
  factures: page("factures", () => <DgFactures />),
};
