from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
from typing import Optional


class ExtractedItemSchema(BaseModel):
    """Exigence textuelle + référence source (besoins, critères, prérequis,
    ressources, vigilance). Tolère l'ancien format `str` à l'entrée (caches/
    payloads hérités, mocks frontend) → coercion vers {texte, source_section}."""
    texte: str = ""
    source_section: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, v):
        if isinstance(v, str):
            return {"texte": v}
        if isinstance(v, dict):
            return v
        # dataclass ExtractedItem (ou tout objet portant .texte)
        texte = getattr(v, "texte", None)
        if texte is not None:
            return {"texte": texte, "source_section": getattr(v, "source_section", "")}
        return v


class BidRecommendationSchema(str, Enum):
    GO = "GO"
    NO_BID = "NO_BID"
    CONDITIONAL = "CONDITIONAL"


class KeyElementSchema(BaseModel):
    category: str
    value: str
    confidence: float = 1.0


class MatchedDocumentSchema(BaseModel):
    doc_id: str
    filename: str
    doc_type: str
    relevance_score: float
    excerpt: str


class MarketIdentitySchema(BaseModel):
    type_marche: str = ""
    reference: str = ""
    autorite_contractante: str = ""
    duree_contrat: str = ""
    date_demarrage: str = ""
    deadline_soumission: str = ""
    validite_offre: str = ""
    perimetre_geographique: str = ""
    eligibilite_candidat: str = ""
    confidence: float = 0.0


class CalendarEventSchema(BaseModel):
    label: str
    date: str
    criticite: str = "INFO"
    source_section: str = ""


class EvaluationModalitiesSchema(BaseModel):
    ponderation_technique: int = 0
    ponderation_financiere: int = 0
    seuil_minimum_technique: int = 0
    formule_notation_financiere: str = ""
    modalites: list[str] = []
    confidence: float = 0.0


class ScoringCriterionSchema(BaseModel):
    id: str
    label: str
    max_points: int
    category: str = ""
    is_inferred: bool = False
    estimated_score: int = 0
    risk_level: str = "MODÉRÉ"
    rationale: str = ""
    sources_ged: list[str] = []


class RiskSchema(BaseModel):
    label: str
    criticite: str = "MODÉRÉ"
    pourquoi: str = ""
    mitigation: str = ""
    items_affected: list[str] = []


class PreconditionSchema(BaseModel):
    label: str
    type: str = "ADMIN"
    deadline: str = ""
    responsable: str = ""
    status: str = "PENDING"
    blocking: bool = False
    pieces_requises: list[str] = []


class AppendixSchema(BaseModel):
    code: str
    label: str
    type: str = "ADMIN"
    obligatoire: bool = True
    langue: str = ""
    responsable: str = ""
    deadline_interne: str = ""
    statut: str = "PENDING"
    source_section: str = ""
    note: str = ""


class RequiredProfileSchema(BaseModel):
    profil: str
    domaine: str = ""
    quantite: int = 0
    niveau: str = ""
    experience_min: str = ""
    competences: list[str] = []
    certifications: list[str] = []
    missions: list[str] = []
    rattachement: str = ""
    source_section: str = ""


class EligibilityThresholdSchema(BaseModel):
    libelle: str
    valeur: str = ""
    unite: str = ""
    type: str = "AUTRE"
    blocking: bool = True
    source_section: str = ""


class FinancialDataSchema(BaseModel):
    budget_estime: str = ""
    modalites_paiement: str = ""
    garantie_soumission: str = ""
    penalites: str = ""
    source_section: str = ""


class CapabilityDealSchema(BaseModel):
    client: str
    title: str
    year: str = ""
    status: str = ""
    source: str = "opportunité"


class CapabilityMatchSchema(BaseModel):
    theme: str
    confidence: str = "MOYENNE"
    is_critical: bool = False
    won_count: int = 0
    clients: list[str] = []
    deals: list[CapabilityDealSchema] = []


class ClientContextSchema(BaseModel):
    matched: bool = False
    odoo_client_name: str = ""
    match_confidence: str = ""
    city: str = ""
    country: str = ""
    known_contact: str = ""
    is_existing_client: bool = False
    first_interaction: str = ""
    last_interaction: str = ""
    account_owner: str = ""
    opportunities_total: int = 0
    opportunities_won: int = 0
    opportunities_lost: int = 0
    win_rate_pct: int = 0
    open_opportunities: list[str] = []
    orders_count: int = 0
    deployed_technologies: list[str] = []
    invoices_total: int = 0
    invoices_paid: int = 0
    invoices_overdue: int = 0
    payment_reliability: str = ""
    relationship_signals: list[str] = []
    relationship_risks: list[str] = []
    notes: str = ""


class ScoringResultSchema(BaseModel):
    ao_filename: str
    summary: str
    key_elements: list[KeyElementSchema]
    matched_documents: list[MatchedDocumentSchema]
    gaps_analysis: str
    strengths: list[str]
    risks: list[RiskSchema]
    score: int = Field(ge=0, le=100)
    score_basis: str = "GRILLE"  # GRILLE | ESTIME | INDISPONIBLE
    # Scores de préparation par volet : technique = alias du score global (grille technique),
    # financier/administratif = jugement LLM de notre capacité sur ce volet (0 par défaut si non calculé).
    score_technique: int = Field(default=0, ge=0, le=100)
    score_financier: int = Field(default=0, ge=0, le=100)
    score_administratif: int = Field(default=0, ge=0, le=100)
    financier_rationale: str = ""
    administratif_rationale: str = ""
    recommendation: BidRecommendationSchema
    justification: str
    criteres_selection: list[ExtractedItemSchema] = []
    besoins: list[ExtractedItemSchema] = []
    prerequis: list[ExtractedItemSchema] = []
    ressources_demandees: list[ExtractedItemSchema] = []
    points_vigilance: list[ExtractedItemSchema] = []
    date_remise: str = ""
    team_matches: list[MatchedDocumentSchema] = []
    similar_projects: list[MatchedDocumentSchema] = []
    market_identity: MarketIdentitySchema = Field(default_factory=MarketIdentitySchema)
    calendar: list[CalendarEventSchema] = []
    evaluation_modalities: EvaluationModalitiesSchema = Field(default_factory=EvaluationModalitiesSchema)
    criteria_breakdown: list[ScoringCriterionSchema] = []
    preconditions: list[PreconditionSchema] = []
    preconditions_incomplete: bool = False
    appendices: list[AppendixSchema] = []
    appendices_incomplete: bool = False
    profils_demandes: list[RequiredProfileSchema] = []
    seuils_eligibilite: list[EligibilityThresholdSchema] = []
    donnees_financieres: FinancialDataSchema = Field(default_factory=FinancialDataSchema)
    client_context: ClientContextSchema = Field(default_factory=ClientContextSchema)
    capability_matches: list[CapabilityMatchSchema] = []
    capability_gaps: list[str] = []


class PartnerSchema(BaseModel):
    name: str
    role: str = "membre_groupement"
    type: str = "entreprise"


class PhaseActionSchema(BaseModel):
    day_label: str
    action: str
    responsable: str = ""
    duree_estimee: str = ""
    deliverable: str = ""
    statut: str = "PENDING"


class StrategyPhaseSchema(BaseModel):
    id: str
    name: str
    description: str = ""
    start_day: str = ""
    end_day: str = ""
    actions: list[PhaseActionSchema] = []
    prerequisites: list[str] = []
    is_blocking_next: bool = False


class BidStrategyRequest(BaseModel):
    scoring_result: ScoringResultSchema
    client_name: Optional[str] = None
    decision: str = "GO"
    decision_reason: Optional[str] = None
    partner: Optional[PartnerSchema] = None


class BidStrategySchema(BaseModel):
    phases: list[StrategyPhaseSchema] = []
    strategy_text: str = ""
    response_plan: str = ""
    appendices: list[AppendixSchema] = []
    partner: Optional[PartnerSchema] = None
    partner_validation: list[PreconditionSchema] = []
    version: int = 1
    parent_version: Optional[int] = None
    generated_at: str = ""


class AnalysisExportRequest(BaseModel):
    scoring_result: ScoringResultSchema
    client_name: Optional[str] = None


class StrategyExportRequest(BaseModel):
    scoring_result: ScoringResultSchema
    bid_strategy: BidStrategySchema
    client_name: Optional[str] = None
    decision: str = "GO"


class ChecklistExportRequest(BaseModel):
    ao_filename: str
    client_name: Optional[str] = None
    submission_date: str = ""
    # Pièces réelles extraites de l'AO (avec statut édité côté frontend).
    # Si vide → l'export retombe sur une checklist générique inférée.
    appendices: list[AppendixSchema] = []


# ── Matrice de conformité : confirmation humaine (cochage) ────────────────────
class MatrixConfirmationItem(BaseModel):
    """Un cochage humain sur une exigence de la matrice de conformité."""
    id: str
    statut_confirme: Optional[str] = None      # statut VALIDÉ (CONFORME / NON_CONFORME / …)
    domaine_valide: Optional[str] = None
    commentaire: Optional[str] = None
    confirme: bool = True                       # False = lever une confirmation existante


class MatrixConfirmRequest(BaseModel):
    ao_filename: str
    confirme_par: str = ""                       # email/nom du valideur
    confirmations: list[MatrixConfirmationItem] = []


class OfferGenerationRequest(BaseModel):
    ao_filename: str
    scoring_result: ScoringResultSchema
    client_name: Optional[str] = None
    additional_context: Optional[str] = None
    # Documents GED choisis par l'utilisateur (noms de fichiers). Vide → repli sur le
    # matching automatique (CV) / aucune section références (ABE).
    selected_cvs: list[str] = []
    selected_abes: list[str] = []


class OfferGenerationResponse(BaseModel):
    filename: str
    message: str


# ── Offre en 2 temps : plan de document IA → rendu .docx ──────────────────────
# L'IA ne remplit plus un gabarit : elle produit un PLAN DE DOCUMENT (couverture +
# blocs typés) que le builder met en forme sans template. Cf. offer_docx_builder.

class OfferCoverSchema(BaseModel):
    """Page de garde rédigée par l'IA (le client et la date sont ajoutés par le code)."""
    titre: str = ""
    sous_titre: str = "Offre technique"
    accroche: str = ""


class OfferBlockSchema(BaseModel):
    """Un bloc de contenu. `type` ∈ heading | paragraph | bullets | numbered | table |
    page_break. Seuls les champs pertinents pour le `type` sont utilisés au rendu."""
    type: str = "paragraph"
    level: int = 1                       # heading
    text: str = ""                       # heading / paragraph
    items: list[str] = []                # bullets / numbered
    titre: str = ""                      # table
    headers: list[str] = []              # table
    rows: list[list[str]] = []           # table

    @field_validator("items", mode="before")
    @classmethod
    def _coerce_items(cls, v):
        if v is None:
            return []
        return [("" if i is None else str(i)) for i in v] if isinstance(v, list) else []

    @field_validator("rows", mode="before")
    @classmethod
    def _coerce_rows(cls, v):
        if not isinstance(v, list):
            return []
        return [[("" if c is None else str(c)) for c in r] for r in v if isinstance(r, list)]


class OfferSectionsSchema(BaseModel):
    """Plan de document produit par l'IA : couverture + liste de blocs."""
    cover: OfferCoverSchema = Field(default_factory=OfferCoverSchema)
    blocks: list[OfferBlockSchema] = []


class OfferSectionsResponse(BaseModel):
    sections: OfferSectionsSchema
    domain: str = ""
    client_name: str = ""
    filename: str = ""


class OfferRenderRequest(BaseModel):
    ao_filename: str
    scoring_result: ScoringResultSchema
    sections: OfferSectionsSchema
    client_name: Optional[str] = None
    # CV / ABE choisis dans le modal (noms de fichiers GED) à injecter dans le .docx.
    selected_cvs: list[str] = []
    selected_abes: list[str] = []


class TeamMatchRequest(BaseModel):
    requirements: list[str]
    ao_context: str = ""
    top_k: int = 6

class TeamMatchProfile(BaseModel):
    filename: str
    name: str
    excerpt: str
    relevance_score: float
    match_reasons: list[str] = []

class TeamMatchResponse(BaseModel):
    profiles: list[TeamMatchProfile]
    query_used: str
