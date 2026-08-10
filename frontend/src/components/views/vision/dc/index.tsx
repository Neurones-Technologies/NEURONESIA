import { ReactNode } from "react";
import { DcPipeline } from "./DcPipeline";
import { DcBaseInstallee } from "./DcBaseInstallee";
import { DcMixOffre } from "./DcMixOffre";
import { DcTransformation } from "./DcTransformation";

/** Registre des onglets du cockpit DC : chaque clé est un segment d'URL
 * (`/dc/vision/<clé>`) et doit avoir son entrée dans `VISION_SECTIONS.dc`
 * (cf. lib/data/sections.ts) — sinon le menu affiche un onglet sans page, ou
 * l'inverse. La route valide le segment avant d'appeler ce registre. */
export const DC_SECTIONS: Record<string, () => ReactNode> = {
  pipeline: () => <DcPipeline />,
  "base-installee": () => <DcBaseInstallee />,
  "mix-offre": () => <DcMixOffre />,
  transformation: () => <DcTransformation />,
};
