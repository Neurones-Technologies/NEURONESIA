import { apiFetch } from "./client";

export interface YearStats {
  year: number;
  clients_with_orders: number;
  orders_count: number;
  revenue_xof: number;
}

export interface MonthStat {
  mois: number;
  ca_xof: number;
  nb_commandes: number;
}

export interface OpenPipelineStats {
  total_opportunites: number;
  [key: string]: unknown;
}

export interface WinRate {
  gagnees_nb: number;
  perdues_nb: number;
  taux_nb_pct: number;
  gagnees_valeur_xof: number;
  perdues_valeur_xof: number;
  taux_valeur_pct: number;
}

export interface YtdStats extends YearStats {
  /** Jour calendaire (ISO) auquel `year`/`previous_year` équivalents sont
   * arrêtés — permet de comparer deux exercices à date comparable, contrairement
   * à `year`/`previous_year` qui comparent une année en cours à une année pleine. */
  as_of: string;
}

export interface Kpis {
  year: YearStats;
  previous_year: YearStats;
  ytd: YtdStats;
  previous_ytd: YtdStats;
  monthly: MonthStat[];
  monthly_previous: MonthStat[];
  open_pipeline: OpenPipelineStats;
  win_rate: WinRate;
  marges: {
    nb_dossiers: number;
    perc_marge_provisoire_moyen: number;
    perc_marge_definitive_moyen: number;
    [key: string]: unknown;
  };
}

export async function getKpis(year?: number): Promise<Kpis> {
  const q = year ? `?year=${year}` : "";
  return apiFetch<Kpis>(`/v1/dashboard/kpis${q}`);
}

export interface MonthClient {
  client: string;
  nb_commandes: number;
  ca_xof: number;
}

export interface MonthlyClients {
  year: number;
  /** Clé = numéro du mois (1-12) en string, tel que sérialisé par FastAPI. */
  months: Record<string, MonthClient[]>;
}

export async function getMonthlyClients(year?: number, limit = 10): Promise<MonthlyClients> {
  const params = new URLSearchParams();
  if (year) params.set("year", String(year));
  params.set("limit", String(limit));
  return apiFetch<MonthlyClients>(`/v1/dashboard/monthly-clients?${params.toString()}`);
}

export interface ForecastScenarios {
  nb_opportunites: number;
  realiste_xof: number;
  pessimiste_xof: number;
  optimiste_xof: number;
  total_pipeline_xof: number;
  avg_probability_pct: number;
}

export interface ForecastOpportunity {
  name: string;
  client: string;
  stage: string;
  value_xof: number;
  probability_pct: number;
  commercial: string;
  deadline: string | null;
  created_at: string | null;
  age_days: number;
  month_offset: number;
  at_risk: boolean;
  weighted_xof: number;
}

export interface ForecastByClient {
  client: string;
  nb_opportunites: number;
  opportunities: ForecastOpportunity[];
  total_xof: number;
  weighted_xof: number;
  at_risk_xof: number;
  min_month_offset: number;
}

export interface ForecastPipelineWeighted {
  scenarios: ForecastScenarios;
  opportunities: ForecastOpportunity[];
  by_stage: Array<{ stage: string; weighted_xof: number }>;
  by_client: ForecastByClient[];
  month_labels: string[];
}

export async function getForecastPipelineWeighted(): Promise<ForecastPipelineWeighted> {
  return apiFetch<ForecastPipelineWeighted>("/v1/dashboard/forecast/pipeline-weighted");
}

export interface OfferMixFamily {
  family: string;
  label: string;
  nb: number;
  montant_xof: number;
  montant_pondere_xof: number;
  /** Part du montant CLASSÉ, pas du pipe total — cf. `coverage`. */
  part_montant_pct: number;
  part_nb_pct: number;
  win_rate_pct: number;
  nb_closes: number;
}

/** Fraction du pipe sur laquelle portent réellement les parts par famille. La
 * famille d'offre est déduite du libellé (Odoo ne porte aucune catégorie sur
 * l'opportunité), donc une part du pipe reste inclassable — à afficher, sans
 * quoi « Réseau 36 % » se lit comme 36 % du pipe au lieu de 36 % du classé. */
export interface OfferMixCoverage {
  nb_total: number;
  nb_classe: number;
  nb_non_classe: number;
  couverture_nb_pct: number;
  montant_total_xof: number;
  montant_classe_xof: number;
  montant_non_classe_xof: number;
  couverture_montant_pct: number;
}

export interface OfferMixPeriod {
  period: string;
  montant_total_xof: number;
  nb_total: number;
  vide: boolean;
  /** Échéance déjà passée : à ne pas présenter comme du forecast. */
  echu: boolean;
  courant: boolean;
  families: Array<{
    family: string;
    label: string;
    nb: number;
    montant_xof: number;
    part_montant_pct: number;
  }>;
}

export interface OfferMix {
  families: OfferMixFamily[];
  coverage: OfferMixCoverage;
  periods: OfferMixPeriod[];
  /** "echeance" : l'axe temporel porte les dates de clôture prévue. */
  axe_temporel: string;
  hors_fenetre: { nb: number; montant_xof: number };
  sans_echeance: { nb: number; montant_xof: number };
  echu: { nb: number; montant_xof: number; part_montant_pct: number };
  dominante: {
    family: string | null;
    label: string | null;
    part_montant_pct: number;
    /** `null` quand les deux trimestres comparés n'ont pas assez de volume. */
    delta_part_pct: number | null;
  };
  /** `false` tant que la ventilation vient des échéances et non de snapshots
   * quotidiens : c'est une projection, pas une tendance mesurée. */
  historique_reel: boolean;
  nb_closes: number;
  nb_annulees: number;
}

export async function getOfferMix(): Promise<OfferMix> {
  return apiFetch<OfferMix>("/v1/dashboard/offer-mix");
}

/** Compte du portefeuille, vu par le suivi de dormance. L'impayé est un DRAPEAU et
 * un montant agrégé : le détail par facture est réservé aux profils financiers. */
export interface DormanceAccount {
  compte: string;
  client_id: string | null;
  segment: string;
  label: string;
  /** `null` pour un prospect : il n'a jamais commandé, il n'est pas « silencieux ». */
  mois_silence: number | null;
  derniere_commande: string | null;
  nb_commandes: number;
  ca_total_xof: number;
  commercial: string;
  alerte_impaye: boolean;
  impaye_xof: number;
  retard_max_jours: number;
  nb_opp_ouvertes: number;
  opp_ouvertes_xof: number;
  /** Présent dans les commandes mais absent du référentiel clients (défaut de sync Odoo). */
  hors_referentiel: boolean;
}

export interface DormanceSegment {
  segment: string;
  label: string;
  borne: string;
  nb_comptes: number;
  part_nb_pct: number;
  ca_historique_xof: number;
  part_ca_pct: number;
  nb_avec_impaye: number;
  impaye_xof: number;
  nb_avec_opp_ouverte: number;
  pipe_ouvert_xof: number;
  silence_median_mois: number | null;
  comptes: DormanceAccount[];
}

export interface SuiviDormance {
  /** Date d'observation. À AFFICHER : la segmentation glisse d'environ 10 comptes
   * par mois, deux lectures prises à quinze jours d'écart semblent se contredire. */
  as_of: string;
  seuils_mois: { ralentit: number; dormant: number; perdu: number };
  /** Dans l'ordre métier Actif → Prospect, jamais trié par volume. */
  segments: DormanceSegment[];
  /** Comptes Ralentit + Dormant par CA historique — le cœur du suivi d'état. */
  decrochages: DormanceAccount[];
  totaux: {
    nb_comptes: number;
    nb_avec_commande: number;
    nb_prospects: number;
    ca_historique_xof: number;
    ca_a_risque_xof: number;
    nb_decroches: number;
  };
  /** CA historique CUMULÉ des comptes Dormant + Perdu — jamais un manque à gagner
   * de l'exercice. À qualifier à l'écran. */
  sommeil: { ca_historique_xof: number; part_ca_pct: number; nb_comptes: number };
  dormants_avec_impaye: { nb_comptes: number; impaye_xof: number; comptes: DormanceAccount[] };
  qualite_donnees: {
    nb_hors_referentiel: number;
    ca_hors_referentiel_xof: number;
    nb_comptes_ca_nul: number;
  };
  note: string;
}

export async function getAccountActivity(): Promise<SuiviDormance> {
  return apiFetch<SuiviDormance>("/v1/dashboard/account-activity");
}

export interface LostDeal {
  client: string;
  [key: string]: unknown;
}

export interface LostDeals {
  nb_total: number;
  montant_total_xof: number;
  top_deals: LostDeal[];
  by_client: Array<{ client: string; nb: number; montant_xof: number }>;
  by_commercial: Array<{ commercial: string; nb: number; montant_xof: number }>;
}

export interface PerformanceSummary {
  win_rate: WinRate;
  lost_deals: LostDeals;
}

export async function getPerformanceSummary(limit = 20): Promise<PerformanceSummary> {
  return apiFetch<PerformanceSummary>(`/v1/dashboard/performance/summary?limit=${limit}`);
}

export interface UnpaidTopDebtor {
  client: string;
  nb_factures: number;
  montant_total_xof: number;
  retard_max_jours: number;
}

export interface UnpaidExposure {
  exposition_totale_xof: number;
  nb_factures_impayees: number;
  par_statut: Record<string, { nb: number; montant: number }>;
  retard_90j_nb_factures: number;
  retard_90j_montant_xof: number;
  top_10_debiteurs: UnpaidTopDebtor[];
}

export interface Unpaid {
  exposure: UnpaidExposure;
  top_invoices: Array<Record<string, unknown>>;
}

export async function getUnpaid(limit = 10): Promise<Unpaid | null> {
  return apiFetch<Unpaid | null>(`/v1/dashboard/unpaid?limit=${limit}`, { allowForbidden: true });
}

export interface UnpaidAnalysis {
  analysis: string;
  context: Record<string, unknown>;
}

export async function getUnpaidAnalysis(): Promise<UnpaidAnalysis | null> {
  return apiFetch<UnpaidAnalysis | null>("/v1/dashboard/unpaid/analysis", {
    method: "POST",
    allowForbidden: true,
  });
}

export interface Dso {
  error?: string;
  client: string;
  annee: number | null;
  total_factures: number;
  payees: number;
  en_attente: number;
  taux_recouvrement_pct: number;
  montant_total_xof: number;
  montant_paye_xof: number;
  montant_en_attente_xof: number;
  delai_moyen_recouvrement_reel_jours: number | null;
  delai_moyen_accorde_jours: number | null;
  retard_moyen_impayes_jours: number;
  nb_impayes_en_souffrance: number;
  dso_approx_jours: number | null;
  note: string;
}

export async function getDso(client = "", year?: number): Promise<Dso | null> {
  const params = new URLSearchParams();
  if (client) params.set("client", client);
  if (year) params.set("year", String(year));
  const q = params.toString();
  return apiFetch<Dso | null>(`/v1/dashboard/dso${q ? `?${q}` : ""}`, { allowForbidden: true });
}

export interface MarginStats {
  annee: number;
  nb_dossiers: number;
  ca_provisoire_total: number;
  ca_definitif_total: number;
  marge_provisoire_total: number;
  marge_definitive_total: number;
  perc_marge_provisoire_moyen: number;
  perc_marge_definitive_moyen: number;
  total_encaisse: number;
  reste_a_encaisser: number;
  backlog_total: number;
  fournisseurs_payes: number;
  fournisseurs_restant: number;
}

export interface Margins {
  stats: MarginStats;
  top_dossiers: Array<Record<string, unknown>>;
}

export async function getMargins(year?: number, limit = 10): Promise<Margins> {
  const params = new URLSearchParams();
  if (year) params.set("year", String(year));
  params.set("limit", String(limit));
  return apiFetch<Margins>(`/v1/dashboard/margins?${params.toString()}`);
}

export interface BudgetVariance {
  annee: number;
  annee_precedente: number;
  ecart_total_xof: number;
  effet_clients_retenus_xof: number;
  effet_clients_gagnes_xof: number;
  effet_clients_perdus_xof: number;
  top_clients_gagnes: Array<{ client: string; ca_xof: number }>;
  top_clients_perdus: Array<{ client: string; ca_xof: number }>;
  nb_clients_retenus: number;
  nb_clients_gagnes: number;
  nb_clients_perdus: number;
  note: string;
}

export async function getBudgetVariance(year?: number): Promise<BudgetVariance> {
  const q = year ? `?year=${year}` : "";
  return apiFetch<BudgetVariance>(`/v1/dashboard/budget-variance${q}`);
}

export interface NextAction {
  client: string;
  type: string;
  texte: string;
  montant_xof: number;
}

export interface NextActions {
  actions: NextAction[];
  note: string;
}

export async function getNextActions(limit = 10): Promise<NextActions | null> {
  return apiFetch<NextActions | null>(`/v1/dashboard/next-actions?limit=${limit}`, {
    allowForbidden: true,
  });
}

export interface TopClient {
  client: string;
  nb_commandes: number;
  ca_total_xof: number;
  pays: string;
}

export async function getTopClients(year?: number, limit = 10): Promise<TopClient[] | null> {
  const params = new URLSearchParams();
  if (year) params.set("year", String(year));
  params.set("limit", String(limit));
  return apiFetch<TopClient[] | null>(`/v1/dashboard/top-clients?${params.toString()}`, {
    allowForbidden: true,
  });
}

export interface RevenueBySalesperson {
  commercial: string;
  [key: string]: unknown;
}

export async function getRevenueBySalesperson(
  year?: number,
  quarter?: number
): Promise<RevenueBySalesperson[] | null> {
  const params = new URLSearchParams();
  if (year) params.set("year", String(year));
  if (quarter) params.set("quarter", String(quarter));
  const q = params.toString();
  return apiFetch<RevenueBySalesperson[] | null>(
    `/v1/dashboard/revenue/by-salesperson${q ? `?${q}` : ""}`,
    { allowForbidden: true }
  );
}

export interface AnalysisResult {
  analysis: string;
  context?: Record<string, unknown>;
}

export async function getForecastAnalysis(): Promise<AnalysisResult | null> {
  return apiFetch<AnalysisResult | null>("/v1/dashboard/forecast/analysis", {
    method: "POST",
    allowForbidden: true,
  });
}

export async function getPerformanceAnalysis(): Promise<AnalysisResult | null> {
  return apiFetch<AnalysisResult | null>("/v1/dashboard/performance/analysis", {
    method: "POST",
    allowForbidden: true,
  });
}

export async function getMarginsAnalysis(year?: number): Promise<AnalysisResult | null> {
  const q = year ? `?year=${year}` : "";
  return apiFetch<AnalysisResult | null>(`/v1/dashboard/margins/analysis${q}`, {
    method: "POST",
    allowForbidden: true,
  });
}

export async function getTrendAnalysis(
  months: string[],
  valuesMFcfa: number[]
): Promise<AnalysisResult | null> {
  return apiFetch<AnalysisResult | null>("/v1/dashboard/analysis", {
    method: "POST",
    body: JSON.stringify({ months, values_m_fcfa: valuesMFcfa }),
    allowForbidden: true,
  });
}
