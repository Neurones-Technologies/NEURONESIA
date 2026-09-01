import { apiFetch } from "./client";

/** Provenance d'un bloc de données servi par le backend.
 *
 * `"reel"`     mesuré sur le miroir Odoo ;
 * `"statique"` gabarit : la donnée n'existe pas encore dans le système ;
 * `"mixte"`    une part mesurée et une part posée dans le même écran (le Gap :
 *              réalisé mesuré, objectif posé) — jamais dans la même VALEUR.
 *
 * Tout composant qui affiche un bloc autre que `"reel"` DOIT le signaler à
 * l'écran (cf. `SourceKick` / `SourceNote` dans views/vision/dc/shared.ts). Un
 * chiffre de démonstration présenté comme mesuré finit dans une revue de
 * performance et fait prendre une mauvaise décision. */
export type SourceDonnees = "reel" | "statique" | "mixte";

/** Cadence de lecture demandée par le DC : mensuelle, trimestrielle, annuelle. */
export type Periode = "mois" | "trimestre" | "annee";

export const PERIODES: { id: Periode; label: string }[] = [
  { id: "mois", label: "Mensuel" },
  { id: "trimestre", label: "Trimestriel" },
  { id: "annee", label: "Annuel" },
];

export function estPeriode(valeur: string | undefined): valeur is Periode {
  return valeur === "mois" || valeur === "trimestre" || valeur === "annee";
}

// ── Objectifs et Gap ────────────────────────────────────────────────────────

export interface GapPeriode {
  index: number;
  libelle: string;
  objectif_xof: number;
  realise_xof: number;
  nb_commandes: number;
  ecart_xof: number;
  /** `null` sur une période non commencée : un « 0 % » se lirait comme un échec. */
  taux_pct: number | null;
  statut: "revolue" | "en_cours" | "a_venir";
  en_cours: boolean;
  part_ecoulee_pct: number | null;
}

export interface GapCommercial {
  salesperson_id: string | null;
  display_name: string;
  objectif_xof: number;
  /** Vrai quand la règle du gabarit ne peut pas lui attribuer d'objectif
   * (aucun réalisé N-1) : à saisir, et non un objectif de zéro. */
  objectif_absent: boolean;
  motif_objectif_absent: string | null;
  realise_xof: number;
  ecart_xof: number;
  taux_pct: number | null;
  nb_commandes: number;
  part_ca_equipe_pct: number;
}

export interface PorteurNonNominatif {
  display_name: string;
  /** `"technique"` = compte de l'ERP ; `"collectif"` = entité réelle dont le CA
   * existe mais n'est imputable à personne. */
  nature: string | null;
  realise_xof: number;
  nb_commandes: number;
  part_ca_equipe_pct: number;
}

export interface ObjectifsGap {
  source: SourceDonnees;
  origine_objectifs: string;
  regle_gabarit: string | null;
  avertissement: string | null;
  annee: number;
  periode: Periode;
  as_of: string;
  equipe: {
    objectif_annuel_xof: number;
    realise_xof: number;
    ecart_xof: number;
    taux_pct: number | null;
    realise_annee_precedente_xof: number;
    part_ecoulee_annee_pct: number | null;
  };
  periodes: GapPeriode[];
  commerciaux: GapCommercial[];
  porteurs_non_nominatifs: PorteurNonNominatif[];
  couverture: {
    realise_nominatif_xof: number;
    part_nominative_pct: number;
    nb_commerciaux: number;
    nb_porteurs_non_nominatifs: number;
    somme_objectifs_individuels_xof: number;
  };
  annees_disponibles: number[];
  note: string;
}

export async function getObjectifs(annee?: number, periode: Periode = "trimestre"): Promise<ObjectifsGap | null> {
  const q = new URLSearchParams({ periode });
  if (annee) q.set("annee", String(annee));
  return apiFetch<ObjectifsGap | null>(`/v1/commercial/objectifs?${q}`, { allowForbidden: true });
}

// ── Comptes : classement, pics, acquisition ─────────────────────────────────

export interface CompteClasse {
  compte: string;
  client_id: string | null;
  commercial: string;
  /** CA de l'EXERCICE en cours — c'est la lecture du cockpit. */
  ca_realise_xof: number;
  nb_commandes: number;
  /** Cumul depuis l'origine du miroir, servi en CONTEXTE du chiffre d'exercice
   *  (un compte à 100 M cette année qui en a fait 1 900 depuis 2019 ne se lit
   *  pas comme un nouveau venu au même montant). Jamais un substitut. */
  ca_historique_xof: number;
  nb_commandes_historique: number;
  panier_moyen_xof: number;
  nb_opp_a_venir: number;
  pipe_a_venir_xof: number;
  nb_opp_echues: number;
  pipe_echu_xof: number;
  derniere_commande: string | null;
  alerte_impaye: boolean;
  indice_montant: number;
  indice_quantite: number;
  indice_combine: number;
  ecart_lecture: number;
  /** Le compte change de place selon qu'on le juge en quantité ou en montant —
   * exactement le cas que le DC veut voir signalé. */
  lecture_divergente: boolean;
}

export interface Pic {
  compte: string;
  client_id: string;
  commercial: string;
  mois: string;
  mois_en_cours: boolean;
  montant_xof: number;
  nb_commandes_mois: number;
  mediane_mensuelle_xof: number;
  intensite: number;
  nb_mois_historique: number;
}

export interface AnneeAcquisition {
  annee: number;
  nb_comptes: number;
  ca_xof: number;
  comptes: Array<{
    compte: string;
    premiere_commande: string;
    ca_total_xof: number;
    nb_commandes: number;
    commercial: string;
  }>;
}

export interface ComptesDc {
  top_comptes: {
    as_of: string;
    /** Exercice sur lequel portent `ca_realise_xof` et `nb_commandes`. */
    annee: number;
    comptes: CompteClasse[];
    totaux: {
      nb_comptes_classes: number;
      ca_realise_xof: number;
      ca_historique_xof: number;
      pipe_a_venir_xof: number;
      part_ca_top_pct: number;
      part_pipe_top_pct: number;
      nb_lectures_divergentes: number;
    };
    note: string;
  };
  pics: {
    as_of: string;
    fenetre_mois: string[];
    seuils: { facteur: number; montant_plancher_xof: number; min_commandes: number };
    pics: Pic[];
    couverture: {
      nb_comptes_avec_commande: number;
      nb_comptes_eligibles: number;
      nb_pics: number;
      part_eligible_pct: number;
    };
    note: string;
  };
  acquisition: {
    as_of: string;
    annees: AnneeAcquisition[];
    annee_courante: { annee: number; nb_comptes: number; ca_xof: number; nb_comptes_annee_precedente: number };
    vivier: { nb_prospects: number; nb_comptes_avec_commande: number };
    note: string;
  };
}

export async function getComptesDc(limit = 15): Promise<ComptesDc | null> {
  return apiFetch<ComptesDc | null>(`/v1/commercial/comptes?limit=${limit}`, { allowForbidden: true });
}

// ── Qualité du pipe : à closer / à compléter / à requalifier ─────────────────

export interface OpportuniteQualite {
  opp_id: string;
  name: string;
  client: string;
  stage: string;
  montant_xof: number;
  probabilite_pct: number;
  commercial: string;
  deadline: string | null;
  jours_avant_echeance: number | null;
  jours_de_retard: number | null;
  echeance_depassee: boolean;
  defauts: string[];
  defauts_libelles: string[];
  gravite: number;
  motif_closer?: string;
  prioritaire?: boolean;
}

export interface QualitePipe {
  as_of: string;
  totaux: {
    nb_ouvertes: number;
    montant_ouvert_xof: number;
    nb_a_closer: number;
    montant_a_closer_xof: number;
    nb_a_completer: number;
    montant_a_completer_xof: number;
    part_a_completer_pct: number;
    part_montant_a_completer_pct: number;
    nb_a_requalifier: number;
    montant_a_requalifier_xof: number;
    part_montant_a_requalifier_pct: number;
    nb_echeance_depassee: number;
    nb_prioritaires: number;
    nb_sans_commercial: number;
  };
  a_closer: OpportuniteQualite[];
  a_completer: OpportuniteQualite[];
  a_requalifier: OpportuniteQualite[];
  defauts: Array<{ code: string; libelle: string; poids: number; nb_opportunites: number; part_pct: number }>;
  regle: {
    horizon_closer_jours: number;
    motifs_etape_closer: string[];
    champs_completude: Record<string, string>;
  };
  note: string;
}

export async function getQualitePipe(limit = 12): Promise<QualitePipe | null> {
  return apiFetch<QualitePipe | null>(`/v1/commercial/pipeline/qualite?limit=${limit}`, { allowForbidden: true });
}

// ── Cycle de vie des affaires au-dessus du seuil ─────────────────────────────

export interface AffaireTracee {
  opp_id: string;
  name: string;
  client: string;
  stage: string;
  montant_xof: number;
  probabilite_pct: number;
  commercial: string;
  deadline: string | null;
  echeance_depassee: boolean;
  /** `null` quand la date de création est une date d'import en masse — la
   * retenir donnerait une affaire de quatre mois pour un dossier bien plus ancien. */
  creee_le: string | null;
  age_jours: number | null;
  enlisee: boolean;
  derniere_modification: string | null;
}

export interface CycleVie {
  as_of: string;
  seuil_xof: number;
  stock: {
    nb_total: number;
    nb_ouvertes: number;
    nb_closes: number;
    montant_ouvert_xof: number;
    montant_ouvert_pondere_xof: number;
    nb_enlisees: number;
    seuil_enlisement_jours: number;
    part_pipe_ouvert_pct: number;
  };
  par_etape: Array<{ stage: string; nb: number; montant_xof: number }>;
  affaires: AffaireTracee[];
  duree_close: {
    source: SourceDonnees;
    nb_mesurees: number;
    nb_closes_total: number;
    couverture_pct: number;
    mediane_jours: number | null;
    moyenne_jours: number | null;
    /** Faux quand la couverture est trop faible : afficher la couverture, pas le chiffre. */
    exploitable: boolean;
    raison_non_exploitable: string;
  };
  historique_etapes: {
    source: SourceDonnees;
    raison: string;
    avertissement: string;
    durees_par_etape: Array<{ etape: string; duree_mediane_jours: number; part_abandon_pct: number }>;
    profondeur_reelle: {
      nb_instantanes: number;
      premier: string | null;
      dernier: string | null;
      profondeur_jours: number;
      exploitable: boolean;
    };
    mouvement_observe: {
      depuis: string | null;
      jusqu_a: string | null;
      nb_suivies: number;
      nb_changements_etape: number;
      nb_changements_montant: number;
      changements_etape: Array<{
        opp_id: string;
        name: string;
        client: string;
        etape_avant: string;
        etape_apres: string;
        montant_xof: number;
        commercial: string;
      }>;
    };
  };
  note: string;
}

export async function getCycleVie(limit = 15, seuilXof?: number): Promise<CycleVie | null> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (seuilXof) q.set("seuil_xof", String(seuilXof));
  return apiFetch<CycleVie | null>(`/v1/commercial/cycle-vie?${q}`, { allowForbidden: true });
}

// ── Équipe : efficacité, prospection, référentiel ───────────────────────────

export interface LigneEfficacite {
  salesperson_id: string | null;
  display_name: string;
  nature: string | null;
  rang: number;
  indice_efficacite: number | null;
  composantes: {
    transformation: number | null;
    volume_signe: number | null;
    taille_affaire: number | null;
  };
  nb_gagnees: number;
  nb_perdues: number;
  nb_closes: number;
  /** Faux sous le seuil d'affaires closes : le taux reste affiché mais n'entre
   * pas dans l'indice — un 100 % sur trois affaires n'est pas une performance. */
  taux_significatif: boolean;
  taux_nb_pct: number | null;
  taux_valeur_pct: number | null;
  nb_ouvertes: number;
  pipe_ouvert_xof: number;
  montant_gagne_xof: number;
  montant_perdu_xof: number;
  ca_signe_xof: number;
  nb_commandes: number;
  panier_moyen_xof: number;
  ticket_moyen_gagne_xof: number;
}

export interface EquipeDc {
  efficacite: {
    source: SourceDonnees;
    annee: number;
    commerciaux: LigneEfficacite[];
    porteurs_non_nominatifs: LigneEfficacite[];
    periodes_mesure: { transformation: string; ca_signe: string };
    fiabilite: {
      nb_orthographes_observees: number;
      nb_personnes: number;
      nb_doublons_orthographe: number;
      nb_non_nominatifs: number;
      nb_alias_non_confirmes: number;
      nb_opportunites_sans_commercial: number;
      nb_commandes_sans_commercial: number;
      part_ca_nominative_pct: number;
      avertissement: string;
    };
    limites: string[];
    note: string;
    seuil_significativite_closes: number;
  };
  prospection: {
    source: SourceDonnees;
    raison: string;
    avertissement: string;
    annee: number;
    periode: Periode;
    objectif_annuel_nb: number;
    lignes: Array<{
      index: number;
      libelle: string;
      nb_opportunites: number;
      nb_nouveaux_comptes: number;
      montant_genere_xof: number;
      objectif_nb: number;
      ecart_nb: number;
    }>;
    totaux: {
      nb_opportunites: number;
      nb_nouveaux_comptes: number;
      montant_genere_xof: number;
      taux_atteinte_pct: number | null;
    };
    note: string;
  };
  referentiel: {
    personnes: Array<{
      salesperson_id: string;
      display_name: string;
      occurrences: number;
      nb_orthographes: number;
      orthographes: string[];
      sources: string[];
    }>;
    porteurs_non_nominatifs: Array<{
      salesperson_id: string;
      display_name: string;
      occurrences: number;
      nature: string;
      motif: string;
    }>;
    doublons_orthographe: Array<{ display_name: string; orthographes: string[] }>;
    totaux: {
      nb_orthographes_observees: number;
      nb_personnes: number;
      nb_non_nominatifs: number;
      nb_doublons_orthographe: number;
    };
  };
}

export async function getEquipeDc(annee?: number, periode: Periode = "mois"): Promise<EquipeDc | null> {
  const q = new URLSearchParams({ periode });
  if (annee) q.set("annee", String(annee));
  return apiFetch<EquipeDc | null>(`/v1/commercial/equipe?${q}`, { allowForbidden: true });
}

// ── Marché : axes, secteurs, veille ─────────────────────────────────────────

export interface AxeStrategique {
  axe: string;
  nb_ouvertes: number;
  montant_ouvert_xof: number;
  montant_pondere_xof: number;
  nb_gagnees: number;
  montant_gagne_xof: number;
  nb_perdues: number;
  montant_perdu_xof: number;
  nb_closes: number;
  part_montant_pct: number;
  win_rate_pct: number | null;
}

export interface SecteurStatique {
  secteur: string;
  ca_xof: number;
  nb_clients: number;
  croissance_pct: number;
  taille_marche_xof: number;
  part_ca_pct: number;
  part_marche_pct: number | null;
}

export interface SignalVeille {
  id: number;
  titre: string;
  url: string;
  detecte_le: string | null;
  publie_le: string | null;
  pays: string;
  axe: string;
  signal: string;
  risque: string;
  offre: string;
  criticite: number;
  so_what: string;
  action: string;
  source: string;
}

export interface MarcheDc {
  axes: {
    source: SourceDonnees;
    axes: AxeStrategique[];
    coverage: {
      nb_non_classe: number;
      montant_non_classe_xof: number;
      couverture_montant_pct: number;
      nb_motifs: number;
      nb_axes: number;
    };
    dominante: AxeStrategique | null;
    note: string;
  };
  secteurs: {
    source: SourceDonnees;
    raison: string;
    avertissement: string;
    secteurs: SecteurStatique[];
    totaux: {
      ca_xof: number;
      nb_clients: number;
      taille_marche_xof: number;
      part_marche_globale_pct: number | null;
    };
    part_marche: { source: SourceDonnees; raison: string; distinction: string };
    couverture_reelle: {
      nb_clients: number;
      nb_avec_secteur: number;
      nb_secteurs_distincts: number;
      couverture_pct: number;
      valeurs: Array<{ secteur: string; nb_clients: number }>;
      verdict: string;
    };
  };
  veille: {
    source: SourceDonnees;
    signaux: SignalVeille[];
    sources: Array<{ nom: string; url: string; active: boolean; dernier_scan: string | null }>;
    qualite: {
      nb_total: number;
      nb_avec_url: number;
      nb_avec_date_publication: number;
      nb_avec_axe: number;
      premier_scan: string | null;
      dernier_scan: string | null;
      part_exploitable_pct: number;
    };
    note: string;
  };
}

export async function getMarcheDc(limit = 12): Promise<MarcheDc | null> {
  return apiFetch<MarcheDc | null>(`/v1/commercial/marche?limit=${limit}`, { allowForbidden: true });
}

// ── Visites terrain ─────────────────────────────────────────────────────────

export interface Visite {
  date: string;
  compte: string;
  interlocuteur: string;
  objet: string;
  prochaine_action: string;
  opportunite_liee: string;
  compte_rendu: boolean;
  mois_ecoules: number | null;
  exemple: boolean;
}

export interface CompteAVisiter {
  compte: string;
  client_id: string | null;
  commercial: string;
  ca_total_xof: number;
  derniere_commande: string | null;
  mois_silence: number | null;
  nb_opp_ouvertes: number;
  derniere_visite: string | null;
  mois_depuis_visite: number | null;
}

export interface FichierVisites {
  source: SourceDonnees;
  raison: string;
  avertissement: string;
  as_of: string;
  seuil_couverture_mois: number;
  visites: Visite[];
  comptes_a_visiter: CompteAVisiter[];
  comptes_couverts: CompteAVisiter[];
  couverture: {
    source: SourceDonnees;
    nb_comptes_actifs: number;
    nb_visites_enregistrees: number;
    nb_comptes_couverts: number;
    nb_comptes_sans_visite: number;
    taux_couverture_pct: number;
    lecture: string;
  };
  contenu_minimal: string[];
  questions_ouvertes: string[];
}

export async function getVisites(limit = 12): Promise<FichierVisites | null> {
  return apiFetch<FichierVisites | null>(`/v1/commercial/visites?limit=${limit}`, { allowForbidden: true });
}

// ── Alertes ─────────────────────────────────────────────────────────────────

export interface AlerteCommerciale {
  alert_key: string;
  alert_type: string;
  severity: "critique" | "attention" | "info";
  subject_ref: string;
  subject_label: string;
  commercial: string;
  montant_xof: number;
  titre: string;
  detail: string;
  action: string;
  /** Date de PREMIÈRE apparition de la clé — d'où « alerte depuis 3 jours »,
   * impossible à calculer sur un miroir qui ne garde que l'état courant. */
  depuis?: string | null;
  ecartee?: boolean;
  motif_ecart?: string;
  lue?: boolean;
}

export interface AlertesDc {
  as_of: string;
  alertes: AlerteCommerciale[];
  totaux: {
    nb_total: number;
    nb_affichees: number;
    nb_critiques: number;
    nb_ecartees: number;
    par_type: Array<{ type: string; libelle: string; nb: number }>;
  };
  diffusion: { canal: string; limite: string };
  note: string;
}

export async function getAlertes(limit = 25): Promise<AlertesDc | null> {
  return apiFetch<AlertesDc | null>(`/v1/commercial/alertes?limit=${limit}`, { allowForbidden: true });
}
