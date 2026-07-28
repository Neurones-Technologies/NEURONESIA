import { ProfileKey, ProfileMeta } from "@/lib/types";

export const META: Record<ProfileKey, ProfileMeta> = {
  dg: {
    code: "DG",
    name: "Direction générale",
    role: "profil 01 · arbitrage",
    ctx: "Miroir Odoo · temps réel",
    week: "aujourd'hui",
    menuLabel: "Arbitrage, atterrissage, dépendances",
  },
  dc: {
    code: "DC",
    name: "Direction commerciale",
    role: "profil 02 · pilotage",
    ctx: "Miroir Odoo · temps réel",
    week: "aujourd'hui",
    menuLabel: "Pipeline, forecast, cross-sell",
  },
  do: {
    code: "DO",
    name: "Direction des opérations",
    role: "profil 03 · livraison",
    ctx: "Miroir Odoo · temps réel",
    week: "aujourd'hui",
    menuLabel: "Backlog, visibilité, fournisseurs",
  },
  df: {
    code: "DF",
    name: "Direction financière",
    role: "profil 04 · cash et marge",
    ctx: "Miroir Odoo · temps réel",
    week: "aujourd'hui",
    menuLabel: "Encaissement, marge, anomalies",
  },
  am: {
    code: "AM",
    name: "Account manager",
    role: "profil 05 · terrain",
    ctx: "Miroir Odoo · temps réel",
    week: "aujourd'hui",
    menuLabel: "Portefeuille, alertes, renouvellements",
  },
};

export const SECTION_LABELS: Record<string, string> = {
  vision: "Cockpit",
  copilot: "Copilote",
  arbitrage: "Arbitrages",
  referentiel: "Données",
  params: "Réglages",
};
