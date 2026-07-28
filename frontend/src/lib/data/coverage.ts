import { Variant } from "@/lib/types";

export interface CoverageRow {
  n: string;
  profil: string;
  feature: string;
  engine: string;
  objects: string;
  status: string;
  variant: Variant;
}

export const COVERAGE_ROWS: CoverageRow[] = [
  { n: "01", profil: "DG", feature: "Briefing de direction hebdomadaire", engine: "narration", objects: "tous", status: "couvert", variant: "s" },
  { n: "02", profil: "DG", feature: "Atterrissage et scénarios", engine: "M3 · M5", objects: "sale.order · account.move · crm.lead", status: "couvert", variant: "s" },
  { n: "03", profil: "DG", feature: "Radar de dépendance", engine: "M1 · M4", objects: "account.move · purchase.order", status: "couvert", variant: "s" },
  { n: "04", profil: "DG", feature: "Explication d'écart budgétaire", engine: "M4 · narration", objects: "account.move.line · product", status: "couvert", variant: "s" },
  { n: "05", profil: "DG", feature: "Interrogation en langage naturel", engine: "sémantique", objects: "couche sémantique", status: "couvert", variant: "s" },
  { n: "06", profil: "DC", feature: "Crédibilité du forecast", engine: "M5", objects: "crm.lead + snapshots", status: "couvert", variant: "s" },
  { n: "07", profil: "DC", feature: "Opportunités à risque", engine: "M5 · M1", objects: "crm.lead · mail.activity", status: "couvert", variant: "s" },
  { n: "08", profil: "DC", feature: "Ciblage cross-sell chiffré", engine: "M1 · sémantique", objects: "sale.order.line · res.partner", status: "couvert", variant: "s" },
  { n: "09", profil: "DC", feature: "Analyse des motifs de perte", engine: "M5 · narration", objects: "crm.lead · crm.lost.reason", status: "couvert", variant: "s" },
  { n: "10", profil: "DC", feature: "Coaching de portefeuille", engine: "M5 · narration", objects: "crm.lead + snapshots", status: "couvert", variant: "s" },
  { n: "11", profil: "DO", feature: "Consommation du backlog vs plan", engine: "M3", objects: "sale.order.line · account.move.line", status: "proxy", variant: "w" },
  { n: "12", profil: "DO", feature: "Mois de visibilité par practice", engine: "M3", objects: "sale.order · account.move", status: "proxy", variant: "w" },
  { n: "13", profil: "DO", feature: "Détection de dérive d'affaire", engine: "M3", objects: "sale.order.line · account.move.line", status: "proxy", variant: "w" },
  { n: "14", profil: "DO", feature: "Fiabilité fournisseurs", engine: "M2", objects: "purchase.order · account.move", status: "couvert", variant: "s" },
  { n: "15", profil: "DO", feature: "Tension sur la sous-traitance", engine: "M4", objects: "purchase.order.line", status: "couvert", variant: "s" },
  { n: "16", profil: "DF", feature: "Prévision d'encaissement comportementale", engine: "M2", objects: "account.move · account.payment", status: "couvert", variant: "s" },
  { n: "17", profil: "DF", feature: "Dérive du délai de paiement", engine: "M2", objects: "account.move · payment.term", status: "couvert", variant: "s" },
  { n: "18", profil: "DF", feature: "Surveillance de l'exposition", engine: "M1 · M2", objects: "res.partner · account.move", status: "couvert", variant: "s" },
  { n: "19", profil: "DF", feature: "Effet ciseau achat / vente", engine: "M4", objects: "purchase.order.line · sale.order.line", status: "couvert", variant: "s" },
  { n: "20", profil: "DF", feature: "Détection d'anomalies de facturation", engine: "M3 · M4", objects: "sale.order · account.move · purchase.order", status: "couvert", variant: "s" },
  { n: "21", profil: "AM", feature: "Fiche compte avant rendez-vous", engine: "narration", objects: "tous", status: "couvert", variant: "s" },
  { n: "22", profil: "AM", feature: "Next best action", engine: "M1 · M3 · narration", objects: "tous", status: "couvert", variant: "s" },
  { n: "23", profil: "AM", feature: "Alerte rupture de rythme", engine: "M1", objects: "sale.order · account.move", status: "couvert", variant: "s" },
  { n: "24", profil: "AM", feature: "Radar renouvellement et obsolescence", engine: "M1 · M3", objects: "account.move.line · product.template", status: "couvert", variant: "s" },
  { n: "25", profil: "AM", feature: "Aide à la rédaction contextualisée", engine: "narration", objects: "tous", status: "couvert", variant: "s" },
  { n: "26", profil: "tous", feature: "File d'arbitrage priorisée", engine: "M1 à M5 · narration", objects: "sorties de moteurs", status: "couvert", variant: "s" },
  { n: "27", profil: "tous", feature: "Dossier d'arbitrage et options chiffrées", engine: "narration · options", objects: "sorties de moteurs", status: "couvert", variant: "s" },
  { n: "28", profil: "tous", feature: "Engagements et revues", engine: "registre", objects: "registre de décisions", status: "couvert", variant: "s" },
  { n: "29", profil: "tous", feature: "Fiabilité des recommandations", engine: "registre · instantanés", objects: "registre + instantanés", status: "2 moteurs non mesurables", variant: "w" },
];
