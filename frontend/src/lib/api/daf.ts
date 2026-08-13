import { apiFetch } from "./client";
import { SourceDonnees } from "./commercial";

/** Client des trois tableaux de bord du DAF (note « Point DAF financier » du
 * 04/08/2026) et du volet formation.
 *
 * `SourceDonnees` est réutilisé depuis `commercial.ts` : c'est le même contrat de
 * provenance (`reel` / `statique` / `mixte`) et la même règle d'affichage — un
 * bloc non mesuré ne s'affiche jamais nu (cf. `views/vision/dc/source.tsx`, dont
 * les composants sont partagés avec les écrans DAF).
 *
 * Les endpoints sont appelés avec `allowForbidden` : un profil sans la vue
 * `tresorerie` ou `couts` reçoit `null` et l'écran affiche une explication, au
 * lieu de faire tomber la page en erreur. */

// ── Tableau de bord n°1 — Budget ────────────────────────────────────────────

export interface ComposantePerformance {
  code: string;
  libelle: string;
  poids_pct: number;
  /** `null` quand la composante n'est pas mesurable : elle est alors écartée de
   * l'indice et le poids restant est renormalisé. */
  valeur: number | null;
  unite: string;
  cible: number;
  /** `"bas"` = plus petit est meilleur (DSO, consommation budgétaire). */
  sens: "haut" | "bas";
  taux_atteinte_pct: number | null;
  retenue: boolean;
  source: SourceDonnees;
  mesure: string;
  commentaire: string;
}

export interface Performance {
  source: SourceDonnees;
  annee: number;
  as_of: string;
  indice_pct: number | null;
  verdict: string;
  composantes: ComposantePerformance[];
  poids_retenu_pct: number;
  composantes_ecartees: string[];
  regle: string;
  avertissement: string | null;
  note: string;
}

export interface ResultatNet {
  source: SourceDonnees;
  annee: number;
  as_of: string;
  mois_ecoules: number;
  marge_brute_xof: number;
  marge_brute_mesuree: boolean;
  /** Lecture de marge utilisée : `"dossiers"` si l'imputation des dépenses le
   * permet, `"flux"` (CA signé moins achats engagés) sinon. */
  marge_brute_lecture: "dossiers" | "flux";
  marge_brute_exploitable: boolean;
  charges_structure_xof: number;
  charges_structure_mensuelles_xof: number;
  resultat_avant_impot_xof: number;
  taux_is_pct: number;
  impot_xof: number;
  resultat_net_projete_xof: number;
  taux_resultat_net_pct: number;
  ca_reference_xof: number;
  charges_detail: Array<{
    poste: string;
    nature: string;
    montant_mensuel_xof: number;
    montant_periode_xof: number;
    part_pct: number;
  }>;
  raison: string;
  avertissement: string;
  note: string;
}

export interface MargeBrute {
  source: SourceDonnees;
  annee: number;
  as_of: string;
  ca_realise_xof: number;
  depenses_xof: number;
  marge_xof: number;
  taux_pct: number;
  lecture_retenue: "dossiers" | "flux";
  marge_retenue_xof: number;
  ca_retenu_xof: number;
  /** `null` sur un exercice sans aucun CA : un 0 % se lirait comme un effondrement. */
  taux_retenu_pct: number | null;
  lecture_flux: {
    ca_signe_xof: number;
    achats_engages_xof: number;
    marge_xof: number;
    taux_pct: number;
    nb_commandes_vente: number;
    nb_commandes_achat: number;
    limites: string;
  };
  cible_taux_pct: number;
  marge_provisoire_xof: number;
  ca_provisoire_xof: number;
  taux_provisoire_pct: number;
  couverture: {
    nb_dossiers_exercice: number;
    nb_dossiers_imputes: number;
    ca_exercice_xof: number;
    ca_impute_xof: number;
    couverture_pct: number;
    seuil_exploitable_pct: number;
    exploitable: boolean;
    raison_non_exploitable: string;
  };
  serie_mensuelle: Array<{
    mois: number;
    libelle: string;
    ca_xof: number;
    depense_xof: number;
    marge_xof: number;
    taux_pct: number;
    nb_dossiers: number;
  }>;
  note: string;
}

export interface Charge {
  rang: number;
  fournisseur: string;
  montant_xof: number;
  nb_commandes: number;
  montant_moyen_xof: number;
  part_pct: number;
  part_cumulee_pct: number;
  derniere_commande: string | null;
  devises: string[];
  ligne_budgetaire: string;
}

export interface TopCharges {
  source: SourceDonnees;
  /** Indicateur marqué « Voté » dans la note du DAF. */
  valide_par_daf: boolean;
  annee: number;
  as_of: string;
  charges: Charge[];
  totaux: {
    montant_total_xof: number;
    nb_fournisseurs: number;
    nb_commandes: number;
    part_top_pct: number;
    montant_top_xof: number;
    montant_exercice_precedent_xof: number;
    variation_pct: number | null;
    nb_commandes_en_devise: number;
  };
  perimetre: string;
  note: string;
}

export interface LigneBudgetaire {
  ligne: string;
  budget_annuel_xof: number;
  consomme_xof: number;
  reste_xof: number;
  consommation_pct: number;
  part_exercice_ecoulee_pct: number | null;
  /** Écart entre le rythme de consommation et la part d'exercice écoulée. */
  ecart_rythme_pts: number;
  nb_commandes: number;
  nb_fournisseurs: number;
  statut: "depasse" | "tendu" | "normal";
  commentaire: string;
  /** Ligne de recueil : ce qu'aucun motif n'a rattaché, à reclasser. */
  ligne_de_recueil: boolean;
  motifs_utilises: string[];
  top_fournisseurs: Array<{ fournisseur: string; montant_xof: number; part_ligne_pct: number }>;
}

export interface LignesBudgetaires {
  source: SourceDonnees;
  annee: number;
  as_of: string;
  lignes: LigneBudgetaire[];
  totaux: {
    budget_total_xof: number;
    consomme_total_xof: number;
    reste_total_xof: number;
    consommation_pct: number;
    part_exercice_ecoulee_pct: number | null;
    nb_lignes_depassees: number;
    nb_lignes_tendues: number;
    nb_commandes_rattachees: number;
    montant_non_rattache_xof: number;
    part_non_rattachee_pct: number;
  };
  regle_mapping: string;
  raison: string;
  avertissement: string;
  note: string;
}

/** Consommation d'achats cumulée, CA signé cumulé et droite de rythme budgétaire —
 * les trois sur la MÊME échelle de montants. Le CA est là pour trancher : une
 * sous-consommation n'est une économie que si le chiffre d'affaires tient. */
export interface BurnDown {
  source: SourceDonnees;
  annee: number;
  as_of: string;
  budget_total_xof: number;
  points: Array<{
    mois: number;
    libelle: string;
    achats_mois_xof: number;
    achats_cumules_xof: number;
    ca_mois_xof: number;
    ca_cumule_xof: number;
    rythme_budget_xof: number;
    ecart_rythme_xof: number;
  }>;
  resume: {
    achats_cumules_xof: number;
    ca_cumule_xof: number;
    rythme_xof: number;
    ecart_rythme_xof: number;
    taux_marge_flux_pct: number;
    mois_couverts: number;
  };
  raison: string;
  avertissement: string;
  note: string;
}

export interface MargeAnnuelle {
  source: SourceDonnees;
  as_of: string;
  cible_pct: number;
  points: Array<{
    annee: number;
    libelle: string;
    ca_impute_xof: number;
    depense_xof: number;
    marge_xof: number;
    taux_pct: number;
    nb_dossiers: number;
    nb_imputes: number;
    couverture_pct: number;
    /** Faux quand trop peu de dossiers portent une dépense : le taux existe mais
     * n'est pas comparable aux exercices voisins — tracé atténué. */
    exploitable: boolean;
    en_cours: boolean;
  }>;
  resume: {
    nb_exercices: number;
    nb_exploitables: number;
    taux_moyen_exploitable_pct: number | null;
    dernier_exercice_exploitable: number | null;
  };
  note: string;
}

export interface BudgetDaf {
  annee: number;
  as_of: string;
  annees_disponibles: number[];
  performance: Performance;
  resultat_net: ResultatNet;
  marge_brute: MargeBrute;
  top_charges: TopCharges;
  lignes_budgetaires: LignesBudgetaires;
  burn_down: BurnDown;
  marge_annuelle: MargeAnnuelle;
}

export async function getBudgetDaf(annee?: number, limit = 10): Promise<BudgetDaf | null> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (annee) q.set("annee", String(annee));
  return apiFetch<BudgetDaf | null>(`/v1/daf/budget?${q}`, { allowForbidden: true });
}

// ── Tableau de bord n°2 — Relation commerciale ──────────────────────────────

export interface Dso {
  source: SourceDonnees;
  annee: number;
  as_of: string;
  /** Délai constaté facture → règlement, sur les factures effectivement réglées. */
  delai_encaissement_moyen_jours: number | null;
  delai_encaissement_median_jours: number | null;
  /** Retard constaté échéance → règlement : l'écart avec le délai ci-dessus est
   * le délai contractuel accordé au client. */
  retard_moyen_jours: number | null;
  retard_median_jours: number | null;
  /** Lecture bilancielle : encours rapporté au CA. Inclut le stock d'impayés
   * anciens, donc bien plus élevé — ce n'est pas une incohérence. */
  dso_encours_jours: number | null;
  cible_dso_jours: number;
  encours_xof: number;
  encours_echu_xof: number;
  encours_a_echoir_xof: number;
  nb_factures_ouvertes: number;
  taux_recouvrement_pct: number;
  ca_exercice_xof: number;
  serie_mensuelle: Array<{
    mois: string;
    libelle: string;
    nb_factures: number;
    montant_encaisse_xof: number;
    delai_moyen_jours: number | null;
    retard_moyen_jours: number | null;
  }>;
  couverture: {
    nb_factures: number;
    nb_reglees_datees: number;
    part_datee_pct: number;
    nb_delais_mesures: number;
  };
  ecart_lectures_jours: number | null;
  note: string;
}

export interface TrancheAge {
  code: string;
  libelle: string;
  nb_factures: number | null;
  montant_xof: number;
  part_pct: number;
}

export interface Dpo {
  source: SourceDonnees;
  raison: string | null;
  avertissement: string | null;
  as_of: string;
  annee: number;
  dpo_jours: number | null;
  retard_moyen_jours?: number | null;
  delai_negocie_moyen_jours: number | null;
  dette_xof: number;
  dette_echue_xof: number;
  nb_factures_fournisseurs: number;
  tranches: TrancheAge[];
  base_mesuree: {
    achats_engages_exercice_xof: number;
    nb_commandes_exercice: number;
    nb_fournisseurs_exercice: number;
    achats_engages_total_xof: number;
    nb_commandes_total: number;
    nb_fiches_fournisseur: number;
    nb_delais_negocies_renseignes: number;
    delai_negocie_moyen_jours: number | null;
  };
  note: string;
}

export interface BalanceAgee {
  source: SourceDonnees;
  as_of: string;
  tranches: TrancheAge[];
  total_xof: number;
  nb_factures: number;
  nb_sans_echeance: number;
  montant_sans_echeance_xof: number;
  note: string;
}

export interface MauvaisPayeur {
  client: string;
  client_id: string | null;
  client_connu: boolean;
  nb_factures: number;
  montant_facture_xof: number;
  nb_factures_reglees: number;
  retard_moyen_regle_jours: number | null;
  /** Faux sous le seuil de factures réglées : le retard reste affiché mais
   * n'entre pas dans l'indice. */
  comportement_significatif: boolean;
  nb_factures_ouvertes: number;
  encours_xof: number;
  encours_echu_xof: number;
  retard_courant_max_jours: number;
  echeance_la_plus_ancienne: string | null;
  part_encours_echu_pct: number;
  indice_risque: number;
  statut: "contentieux" | "en_retard" | "payeur_lent" | "a_jour";
}

export interface MauvaisPayeurs {
  source: SourceDonnees;
  as_of: string;
  clients: MauvaisPayeur[];
  totaux: {
    nb_clients_factures: number;
    nb_clients_a_risque: number;
    nb_contentieux: number;
    nb_payeurs_lents: number;
    nb_clients_arriere_ancien: number;
    encours_arriere_ancien_xof: number;
    encours_echu_total_xof: number;
    part_top5_encours_echu_pct: number;
  };
  regle: {
    composantes: string;
    min_factures_comportement: number;
    plafond_retard_jours: number;
    seuil_contentieux_jours: number;
  };
  note: string;
}

/** Encours client reconstruit mois par mois, ventilé par ancienneté.
 *
 * Reconstruit et non archivé : aucun instantané n'existe dans le système, mais les
 * dates d'émission, d'échéance et de règlement d'une facture suffisent à savoir si
 * elle était ouverte à une date passée. La contrepartie est dans `limite` — un
 * règlement partiel n'est pas datable, la courbe compte la facture entière. */
export interface SerieEncours {
  source: SourceDonnees;
  as_of: string;
  profondeur_mois: number;
  points: Array<{
    mois: string;
    libelle: string;
    total_xof: number;
    nb_factures: number;
    tranches: Array<{
      code: string;
      libelle: string;
      montant_xof: number;
      nb_factures: number;
      part_pct: number;
    }>;
  }>;
  tranches: Array<{ code: string; libelle: string }>;
  evolution: {
    depuis: string | null;
    encours_debut_xof: number;
    encours_fin_xof: number;
    variation_pct: number;
    contentieux_debut_xof: number;
    contentieux_fin_xof: number;
    part_contentieux_debut_pct: number;
    part_contentieux_fin_pct: number;
  };
  limite: string;
  note: string;
}

export interface SerieDso {
  source: SourceDonnees;
  as_of: string;
  fenetre_mois: number;
  cible_jours: number;
  points: Array<{
    mois: string;
    libelle: string;
    delai_moyen_jours: number | null;
    retard_moyen_jours: number | null;
    nb_reglements_mois: number;
    nb_reglements_fenetre: number;
    montant_encaisse_mois_xof: number;
    exploitable: boolean;
    /** Vrai quand le mois porte trop peu de règlements face à l'historique : le
     * point est tracé en pointillé et exclu du résumé — un délai qui monte parce
     * que seuls les règlements tardifs ont été rapatriés n'est pas une dérive. */
    synchronisation_incomplete: boolean;
  }>;
  resume: {
    depuis: string | null;
    delai_debut_jours: number | null;
    dernier_mois_fiable: string | null;
    delai_fin_jours: number | null;
    variation_jours: number | null;
    ecart_cible_jours: number | null;
    pire_mois: string | null;
    pire_delai_jours: number | null;
    nb_mois_au_dessus_cible: number;
    nb_mois_publies: number;
    nb_mois_fiables: number;
    nb_mois_synchronisation_incomplete: number;
  };
  note: string;
}

export interface RelationCommerciale {
  annee: number;
  as_of: string;
  annees_disponibles: number[];
  dso: Dso;
  dpo: Dpo;
  balance_agee: BalanceAgee;
  mauvais_payeurs: MauvaisPayeurs;
  serie_encours: SerieEncours;
  serie_dso: SerieDso;
  cycle_cash: {
    source: SourceDonnees;
    dso_jours: number | null;
    dpo_jours: number | null;
    ecart_jours: number | null;
    lecture: string;
    fiabilite: string;
  };
}

export async function getRelationCommerciale(annee?: number, limit = 15): Promise<RelationCommerciale | null> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (annee) q.set("annee", String(annee));
  return apiFetch<RelationCommerciale | null>(`/v1/daf/relation-commerciale?${q}`, { allowForbidden: true });
}

// ── Tableau de bord n°3 — Trésorerie prévisionnelle ─────────────────────────

export interface CreanceSurveillee {
  invoice_id: string;
  reference: string;
  client: string;
  client_id: string | null;
  montant_xof: number;
  reste_du_xof: number;
  echeance: string;
  jours_avant_echeance: number;
  jours_de_retard: number;
  retard_habituel_client_jours: number | null;
  comportement_significatif: boolean;
  nb_factures_reglees_client: number;
  /** Échéance décalée du retard habituel MESURÉ du client. */
  encaissement_attendu_le: string;
  risque_glissement: boolean;
  devise: string;
}

export interface Vigilance {
  source: SourceDonnees;
  as_of: string;
  horizon_jours: number;
  a_echoir: CreanceSurveillee[];
  echues: CreanceSurveillee[];
  totaux: {
    nb_a_echoir: number;
    montant_a_echoir_xof: number;
    nb_a_echoir_a_risque: number;
    montant_a_echoir_a_risque_xof: number;
    nb_echues: number;
    montant_echu_xof: number;
    nb_contentieux: number;
    montant_contentieux_xof: number;
    retard_global_constate_jours: number;
  };
  methode: string;
  note: string;
}

export interface MoisAtterrissage {
  mois: string;
  annee: number;
  index_mois: number;
  libelle: string;
  libelle_long: string;
  statut: "revolu" | "en_cours" | "a_venir";
  encaissement_constate_xof: number;
  nb_encaissements_constates: number;
  encaissement_prevu_xof: number;
  nb_creances_attendues: number;
  decaissement_constate_xof: number;
  nb_achats_engages: number;
  decaissement_prevu_xof: number;
  encaissement_retenu_xof: number;
  decaissement_retenu_xof: number;
  solde_xof: number;
  solde_cumule_xof: number;
  alerte: boolean;
  source_encaissement: SourceDonnees;
  source_decaissement: SourceDonnees;
  /** Mois révolu dont les règlements ne sont pas tous rapatriés : le creux est un
   * défaut de synchronisation, pas un fait de trésorerie. */
  synchronisation_incomplete: boolean;
}

export interface Atterrissage {
  source: SourceDonnees;
  annee: number;
  as_of: string;
  mois: MoisAtterrissage[];
  totaux: {
    encaissement_constate_xof: number;
    decaissement_constate_xof: number;
    encaissement_prevu_restant_xof: number;
    decaissement_prevu_restant_xof: number;
    solde_prevu_restant_xof: number;
    variation_cumulee_xof: number;
    nb_mois_en_alerte: number;
    run_rate_decaissement_xof: number;
    fenetre_run_rate_mois: number;
  };
  /** Créances attendues avant le mois en cours : exclues du calendrier, aucune
   * donnée ne permettant de dater leur recouvrement. */
  arriere: {
    source: SourceDonnees;
    montant_xof: number;
    nb_creances: number;
    part_encours_pct: number;
    montant_plus_de_2_ans_xof: number;
    part_plus_de_2_ans_pct: number;
    lecture: string;
  };
  hypotheses: string[];
  note: string;
}

export interface TresoreriePrevisionnelle {
  annee: number;
  as_of: string;
  annees_disponibles: number[];
  vigilance: Vigilance;
  atterrissage: Atterrissage;
  position: {
    source: SourceDonnees;
    encours_facture_xof: number;
    encours_echu_xof: number;
    nb_factures_ouvertes: number;
    reste_a_encaisser_dossiers_xof: number;
    backlog_dossiers_xof: number;
    fournisseurs_restant_dossiers_xof: number;
    note: string;
  };
}

export async function getTresoreriePrevisionnelle(
  annee?: number,
  horizonJours?: number,
): Promise<TresoreriePrevisionnelle | null> {
  const q = new URLSearchParams();
  if (annee) q.set("annee", String(annee));
  if (horizonJours) q.set("horizon_jours", String(horizonJours));
  const suffixe = q.toString() ? `?${q}` : "";
  return apiFetch<TresoreriePrevisionnelle | null>(`/v1/daf/tresorerie-previsionnelle${suffixe}`, {
    allowForbidden: true,
  });
}

// ── Volet transverse — Formation ────────────────────────────────────────────

export interface ControleQualite {
  code: string;
  libelle: string;
  objet: string;
  nb_defaut: number;
  nb_total: number;
  part_defaut_pct: number;
  part_conforme_pct: number;
  gravite: "critique" | "attention" | "info";
  /** Vrai quand le défaut relève du raccordement de données, pas de la saisie :
   * aucune formation ne le corrigera seule. */
  structurel: boolean;
  indicateur_casse: string;
  correction: string;
}

export interface ModuleFormation {
  rang: number;
  code: string;
  titre: string;
  public: string;
  duree_min: number;
  objectif: string;
  points: string[];
  risque_si_absent: string;
  controle: ControleQualite | null;
}

export interface Formation {
  source: SourceDonnees;
  as_of: string;
  modules: ModuleFormation[];
  controles: ControleQualite[];
  qualite: {
    score_global_pct: number | null;
    nb_controles: number;
    nb_critiques: number;
    nb_attention: number;
    nb_structurels: number;
    methode: string;
    seuils: { critique_pct: number; attention_pct: number };
  };
  regles_or: string[];
  duree_totale_min: number;
  note: string;
}

export async function getFormation(): Promise<Formation | null> {
  return apiFetch<Formation | null>("/v1/daf/formation", { allowForbidden: true });
}
