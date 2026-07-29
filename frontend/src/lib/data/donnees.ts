import { daysBetween, isSnapshotStat, MirrorSnapshotStat, MirrorTableStat } from "@/lib/api/donnees";
import { formatDate } from "@/lib/format";
import { ProfileKey, Variant } from "@/lib/types";

/** Curation éditoriale de la vue Données : quels domaines et quels moteurs
 * sont pertinents pour chaque profil. Les CHIFFRES (effectif, fraîcheur,
 * profondeur d'historique) ne vivent pas ici — ils viennent en direct de
 * `/v1/stats/mirror` (cf. `lib/api/donnees.ts`) et sont calculés dans
 * `DonneesView`. Ce fichier ne dit que « quoi montrer à qui », jamais « avec
 * quelle valeur ». */

export interface DomainRef {
  label: string;
  /** Clé de table réelle dans la réponse de `/v1/stats/mirror`, ou `null` si
   * le domaine n'a aucune table de miroir correspondante — une absence
   * vérifiée dans `db/models.py`, pas supposée. */
  table: string | null;
  /** Raison de l'absence, affichée uniquement quand `table` est `null`. */
  absentNote?: string;
}

export const DOMAINS: Record<ProfileKey, readonly DomainRef[]> = {
  dg: [
    { label: "Facturation", table: "invoices" },
    { label: "Commandes", table: "sale_orders" },
    { label: "Pipeline", table: "opportunities" },
    { label: "Temps passé", table: null, absentNote: "Aucune feuille de temps n'est répliquée depuis Odoo." },
  ],
  dc: [
    { label: "Pipeline", table: "opportunities" },
    { label: "Historique du pipeline", table: "pipeline_snapshots" },
    {
      label: "Motifs de perte",
      table: null,
      absentNote: "L'opportunité Odoo répliquée ne porte pas de motif de perte structuré.",
    },
    { label: "Concurrence rencontrée", table: null, absentNote: "Aucun champ concurrent dans le miroir." },
  ],
  do: [
    { label: "Commandes fournisseurs", table: "purchase_orders" },
    {
      label: "Réceptions",
      table: null,
      absentNote: "Les bons de réception (stock.picking) ne sont pas répliqués depuis Odoo.",
    },
    { label: "Durées contractuelles", table: "dossiers" },
    { label: "Plan de charge", table: null, absentNote: "Aucune donnée de charge par consultant dans le miroir." },
  ],
  df: [
    { label: "Factures & avoirs", table: "invoices" },
    {
      label: "Règlements",
      table: null,
      absentNote: "Pas de journal de règlements distinct : chaque facture porte sa date de paiement, mais aucun rapprochement bancaire n'est répliqué.",
    },
    { label: "Achats refacturés", table: "purchase_orders" },
    {
      label: "Coût de revient chargé",
      table: null,
      absentNote: "La marge apparente sur achats est disponible ; le coût de revient en main-d'œuvre ne l'est pas, faute de feuilles de temps.",
    },
  ],
  am: [
    { label: "Comptes & contacts", table: "clients" },
    { label: "Commandes", table: "sale_orders" },
    { label: "Parc installé", table: null, absentNote: "Le parc matériel installé n'est pas répliqué depuis Odoo." },
    { label: "Comptes rendus de visite", table: null, absentNote: "Aucun compte rendu de visite structuré dans le miroir." },
  ],
};

export interface CoverageGap {
  question: string;
  raison: string;
}

export const GAPS: Record<ProfileKey, readonly CoverageGap[]> = {
  dg: [
    {
      question: "Où atterrit l'exercice si rien ne signe avant 90 jours ?",
      raison:
        "Le scénario existe, mais il dépend du pipeline pondéré : l'historique d'instantanés est encore trop court pour le fiabiliser (cf. moteur M5 ci-dessous).",
    },
    {
      question: "Quelle est la marge réelle par affaire ?",
      raison:
        "Non calculable : les feuilles de temps ne sont pas dans le miroir Odoo. Seule la marge apparente sur achats refacturés est disponible.",
    },
    {
      question: "Qu'est-ce qui a changé depuis lundi ?",
      raison: "Disponible dans le brief de la nuit, en tête du cockpit.",
    },
  ],
  dc: [
    {
      question: "Quelles affaires dorment depuis plus de 60 jours ?",
      raison: "Disponible dans le Cockpit et le Copilote — calculé sur le moteur M1 (rupture de rythme).",
    },
    {
      question: "Pourquoi perdons-nous sur le prix ?",
      raison: "Non analysable : ni concurrent rencontré ni motif de perte structuré dans le miroir.",
    },
    {
      question: "Quel est mon taux de transformation par étape ?",
      raison:
        "Calculable, mais peu fiable tant que l'historique d'instantanés du pipeline reste aussi court (cf. moteur M5 ci-dessous).",
    },
  ],
  do: [
    {
      question: "Quelle practice a le moins de visibilité ?",
      raison: "Réponse directe dans le Cockpit, calculée sur le moteur M3 (écart backlog / facturation).",
    },
    {
      question: "Quel est le taux d'occupation par consultant ?",
      raison:
        "Non calculable : les feuilles de temps ne sont pas dans le miroir Odoo. Le cockpit raisonne sur la facturation, pas sur la charge.",
    },
    {
      question: "Quels fournisseurs nous mettent en retard ?",
      raison:
        "Fiable pour les commandes fournisseurs synchronisées ; les bons de réception ne le sont pas, donc le retard réel de livraison n'est pas mesurable.",
    },
  ],
  df: [
    {
      question: "Quel est l'effet ciseau achat / vente par practice ?",
      raison:
        "Calculable sur les commandes fournisseurs synchronisées ; sans lignes de commande détaillées par practice partout, le calcul reste global.",
    },
    {
      question: "Quelle est la marge nette par affaire ?",
      raison:
        "Non calculable : ni feuilles de temps ni coût de revient chargé dans le miroir. Seule la marge sur achats refacturés est disponible.",
    },
    {
      question: "Quelles anomalies de facturation cette semaine ?",
      raison: "Détectées par le moteur M4, listées dans le brief de la nuit et instruites depuis Arbitrages.",
    },
  ],
  am: [
    {
      question: "Quels comptes dois-je rappeler cette semaine ?",
      raison: "Disponible en tête du Cockpit — calculé sur le moteur M1 (rupture de rythme).",
    },
    {
      question: "Quel est le potentiel cross-sell de mon portefeuille ?",
      raison: "Estimation disponible sur les comptes synchronisés ; le parc installé n'est pas répliqué depuis Odoo.",
    },
    {
      question: "Quelle marge je dégage sur mes comptes ?",
      raison: "Non calculable à ce profil : la marge par affaire demande les feuilles de temps.",
    },
  ],
};

export interface EngineRef {
  code: "M1" | "M2" | "M3" | "M4" | "M5" | "LLM";
  nom: string;
  role: string;
  nature: string;
  /** Pour M3/M5 : nom de la table de miroir dont l'historique conditionne la
   * fiabilité réelle (`pipeline_snapshots` / `backlog_snapshots`). Sinon
   * absent — la fiabilité est alors fixe, décrite dans `fiabiliteFixe`. */
  snapshotTable?: "pipeline_snapshots" | "backlog_snapshots";
  fiabiliteFixe?: string;
  methode: string;
}

const ALL_ENGINES: Record<EngineRef["code"], EngineRef> = {
  M1: {
    code: "M1",
    nom: "M1 · Rupture de rythme",
    role: "Détecte les ruptures de cadence de commande par compte",
    nature: "statistique",
    fiabiliteFixe: "élevée",
    methode:
      "Compare l'intervalle depuis la dernière commande à l'intervalle médian du compte sur 24 mois. Déclenche au-delà de 2,5 fois la médiane, avec un minimum de 3 commandes d'historique.",
  },
  M2: {
    code: "M2",
    nom: "M2 · Dérive de délai",
    role: "Repère le glissement d'un délai réel par rapport à son engagement",
    nature: "statistique",
    fiabiliteFixe: "élevée",
    methode:
      "Compare le délai réel constaté (paiement client, réception fournisseur) à l'engagement contractuel et à son propre historique. Même calcul, deux sens : encaissement et achats.",
  },
  M3: {
    code: "M3",
    nom: "M3 · Écart backlog / facturation",
    role: "Compare la courbe de facturation réelle à la courbe théorique du contrat",
    nature: "proxy assumé",
    snapshotTable: "backlog_snapshots",
    methode:
      "Proxy assumé : faute de feuilles de temps, l'avancement est estimé au prorata de la durée contractuelle. Recalculé chaque nuit à partir du journal d'instantanés `backlog_snapshots` — jamais reconstituable a posteriori.",
  },
  M4: {
    code: "M4",
    nom: "M4 · Écart prix achat / vente",
    role: "Compare l'évolution du prix d'achat et du prix de vente sur une même référence",
    nature: "règles",
    fiabiliteFixe: "dépend du rattachement facture / commande",
    methode:
      "Rapproche les lignes de commande fournisseur et client sur un référentiel de familles normalisé. Sans ce rattachement, ce moteur ne produit rien d'exploitable.",
  },
  M5: {
    code: "M5",
    nom: "M5 · Scoring pipeline",
    role: "Calibre la probabilité et la crédibilité d'une opportunité",
    nature: "statistique",
    snapshotTable: "pipeline_snapshots",
    methode:
      "Compare, opportunité par opportunité, la probabilité déclarée aux instantanés quotidiens du journal `pipeline_snapshots` pour mesurer la fiabilité réelle du commercial qui la porte. Impossible à calculer sur un miroir qui ne garde que l'état courant.",
  },
  LLM: {
    code: "LLM",
    nom: "LLM · Narration",
    role: "Met les signaux des cinq moteurs en phrases, jamais ne les calcule",
    nature: "modèle de langage",
    fiabiliteFixe: "à relire",
    methode:
      "Seul moteur génératif : il rédige à partir des sorties chiffrées des cinq autres et cite systématiquement le moteur et le seuil déclencheur. Désactivable sans perdre aucun chiffre.",
  },
};

/** Moteurs mobilisés par le Cockpit de chaque profil — cf. les agrégations
 * réellement appelées par `components/views/vision/*Vision.tsx`. */
export const ENGINES_BY_PROFILE: Record<ProfileKey, readonly EngineRef[]> = {
  dg: [ALL_ENGINES.M3, ALL_ENGINES.M4, ALL_ENGINES.M5, ALL_ENGINES.LLM],
  dc: [ALL_ENGINES.M5, ALL_ENGINES.M1, ALL_ENGINES.LLM],
  do: [ALL_ENGINES.M3, ALL_ENGINES.M2, ALL_ENGINES.M4],
  df: [ALL_ENGINES.M2, ALL_ENGINES.M4, ALL_ENGINES.M3],
  am: [ALL_ENGINES.M1, ALL_ENGINES.M3, ALL_ENGINES.LLM],
};

/** Les six moteurs, dans l'ordre canonique — vue globale (Réglages), quand
 * aucune curation par profil n'a de sens. */
export const ENGINES: readonly EngineRef[] = [
  ALL_ENGINES.M1,
  ALL_ENGINES.M2,
  ALL_ENGINES.M3,
  ALL_ENGINES.M4,
  ALL_ENGINES.M5,
  ALL_ENGINES.LLM,
];

/** Fiabilité d'un moteur : fixe pour la plupart, calculée sur la profondeur
 * réelle d'historique du journal d'instantanés pour M3 et M5. `tables` est
 * `null` quand l'appelant n'a pas pu lire le miroir (rôle non-admin sur un
 * écran ouvert à tous, cf. Réglages) — distinct d'un historique réellement
 * absent. */
export function engineFiability(
  engine: EngineRef,
  tables: Record<string, MirrorTableStat | MirrorSnapshotStat> | null
): { label: string; variant: Variant } {
  if (engine.snapshotTable) {
    if (!tables) return { label: "réservé aux administrateurs", variant: "n" };
    const stat = tables[engine.snapshotTable];
    if (!stat || !isSnapshotStat(stat) || stat.count === 0 || !stat.first_date || !stat.last_date) {
      return { label: "historique absent", variant: "r" };
    }
    const depth = daysBetween(stat.first_date, stat.last_date);
    return depth < 60
      ? { label: `en construction · ${depth} j depuis le ${formatDate(stat.first_date)}`, variant: "w" }
      : { label: `établie · ${depth} jours d'historique`, variant: "s" };
  }
  const fixed = engine.fiabiliteFixe ?? "—";
  const variant: Variant = fixed === "élevée" ? "s" : fixed === "à relire" ? "w" : "n";
  return { label: fixed, variant };
}
