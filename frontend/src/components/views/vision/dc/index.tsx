import { ReactNode } from "react";
import { estPeriode, Periode } from "@/lib/api/commercial";
import { vueRetenue, vuesOfSection } from "@/lib/data/sections";
import { VueNav } from "./vue-nav";
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

/** Paramètres d'URL communs aux pages DC.
 *
 * La cadence de lecture (§1 du CR : mensuel, trimestriel, annuel), l'exercice et
 * la vue interne vivent dans la query string plutôt que dans un état client. Les
 * pages restent donc des composants serveur, et une lecture précise se partage par
 * lien — ce qui compte pour un chiffre commenté en revue de performance. */
export interface DcSectionParams {
  periode?: string;
  annee?: string;
  vue?: string;
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

/** Les quatorze écrans du cockpit, par identifiant de vue.
 *
 * Cette table n'a pas changé de contenu depuis le découpage en quatorze pages :
 * ce sont les mêmes composants, avec les mêmes paramètres. Seul leur point de
 * montage a changé — ils sont désormais regroupés par page (cf. `VISION_SECTIONS.dc`). */
const VUES: Record<string, (p: DcSectionParams) => ReactNode> = {
  // Portefeuille
  comptes: () => <DcComptes />,
  pics: () => <DcPics />,
  "base-installee": () => <DcBaseInstallee />,
  // Pipeline
  pipeline: () => <DcPipeline />,
  "pipe-qualite": () => <DcPipeQualite />,
  "cycle-vie": () => <DcCycleVie />,
  // Objectifs et performance
  objectifs: (p) => <DcObjectifs periode={periodeDe(p, "trimestre")} annee={anneeDe(p)} />,
  efficacite: (p) => <DcEfficacite periode={periodeDe(p, "mois")} annee={anneeDe(p)} />,
  prospection: (p) => <DcProspection periode={periodeDe(p, "mois")} annee={anneeDe(p)} />,
  // Marché
  marche: () => <DcMarche />,
  secteurs: () => <DcSecteurs />,
  // Pages à vue unique
  "mix-offre": () => <DcMixOffre />,
  transformation: () => <DcTransformation />,
  visites: () => <DcVisites />,
};

/** Rendu d'une page : ses onglets internes, puis la vue demandée.
 *
 * La vue par défaut est la première déclarée, et une valeur inconnue dans `?vue=`
 * y retombe (cf. `vueRetenue`) : un lien mal recopié ouvre la page plutôt qu'un
 * écran vide. */
function page(section: string) {
  return function rendu(params: DcSectionParams): ReactNode {
    const vues = vuesOfSection("dc", section);
    // Une page à vue unique porte son propre identifiant comme clé de vue.
    const vue = vueRetenue("dc", section, params.vue) ?? section;
    const rendreVue = VUES[vue];
    return (
      <>
        <VueNav
          basePath={`/dc/vision/${section}`}
          vues={vues}
          vue={vue}
          periode={estPeriode(params.periode) ? params.periode : undefined}
          annee={anneeDe(params)}
        />
        {rendreVue ? rendreVue(params) : null}
      </>
    );
  };
}

/** Registre des pages du cockpit DC : chaque clé est un segment d'URL
 * (`/dc/vision/<clé>`) et doit avoir son entrée dans `VISION_SECTIONS.dc`
 * (cf. lib/data/sections.ts) — sinon le menu affiche une entrée sans page, ou
 * l'inverse. La route valide le segment avant d'appeler ce registre, et un test
 * e2e parcourt les deux listes. */
export const DC_SECTIONS: Record<string, (params: DcSectionParams) => ReactNode> = {
  portefeuille: page("portefeuille"),
  pipeline: page("pipeline"),
  objectifs: page("objectifs"),
  marche: page("marche"),
  "mix-offre": page("mix-offre"),
  transformation: page("transformation"),
  visites: page("visites"),
};
