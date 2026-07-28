from dataclasses import dataclass, field
from enum import Enum


class BidRecommendation(str, Enum):
    GO = "GO"
    NO_BID = "NO_BID"
    CONDITIONAL = "CONDITIONAL"


@dataclass
class ExtractedItem:
    """Exigence textuelle extraite de l'AO, AVEC sa référence source.

    Remplace les anciennes `list[str]` (besoins, critères, prérequis, ressources,
    vigilance) : porter `source_section` permet de tracer chaque exigence jusqu'à
    la matrice de conformité (cf. core.domain.requirements). Anti-hallucination :
    `texte` et `source_section` sont repris verbatim de l'AO."""
    texte: str
    source_section: str = ""

    @classmethod
    def coerce(cls, value: object) -> "ExtractedItem":
        """Construit un ExtractedItem depuis une str (ancien format), un dict
        {texte, source_section} (LLM/JSON) ou tout objet portant `.texte`
        (ex: schéma Pydantic). Jamais d'exception : repli sur str(value)."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(texte=value.strip())
        if isinstance(value, dict):
            return cls(
                texte=str(value.get("texte", "") or "").strip(),
                source_section=str(value.get("source_section", "") or "").strip(),
            )
        texte = getattr(value, "texte", None)
        if texte is not None:
            return cls(texte=str(texte or "").strip(),
                       source_section=str(getattr(value, "source_section", "") or "").strip())
        return cls(texte=str(value).strip())


@dataclass
class KeyElement:
    category: str
    value: str
    confidence: float = 1.0


@dataclass
class MatchedDocument:
    doc_id: str
    filename: str
    doc_type: str
    relevance_score: float
    excerpt: str


@dataclass
class MarketIdentity:
    """Fiche d'identité standardisée du marché (extraite littéralement de l'AO)."""
    type_marche: str = ""                    # contrat-cadre, prestation, marché public...
    reference: str = ""                       # ex: ADB/RFP/TCGS/2026/0104
    autorite_contractante: str = ""
    duree_contrat: str = ""                   # "1 an + 2 renouvellements"
    date_demarrage: str = ""
    deadline_soumission: str = ""             # JJ/MM/AAAA HH:MM TZ
    validite_offre: str = ""                  # "120 jours"
    perimetre_geographique: str = ""
    eligibilite_candidat: str = ""            # pays, agréments, groupement
    confidence: float = 0.0                   # 0.0 = non extrait / à clarifier


@dataclass
class CalendarEvent:
    """Événement critique du calendrier de l'AO."""
    label: str                                # "Limite questions clarification"
    date: str                                 # ISO ou format libre tel qu'écrit
    criticite: str = "INFO"                   # BLOQUANT / CRITIQUE / INFO
    source_section: str = ""                  # où dans l'AO


@dataclass
class EvaluationModalities:
    """Modalités d'évaluation de l'offre (pondération, formule, seuils)."""
    ponderation_technique: int = 0            # %
    ponderation_financiere: int = 0           # %
    seuil_minimum_technique: int = 0          # /100
    formule_notation_financiere: str = ""     # "Nf = 100 × Fm / F"
    modalites: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ScoringCriterion:
    """Un item de la grille d'évaluation, scoré individuellement.

    Construit en deux temps :
    - étape 1b (extraction) : id, label, max_points, category, is_inferred
    - étape 4 (scoring + RAG) : estimated_score, risk_level, rationale, sources_ged
    """
    id: str                          # "3.3" ou "ref_similaires"
    label: str                       # "3 références similaires avec attestations"
    max_points: int                  # 15
    category: str = ""               # "Expérience" / "Méthodologie" / "RH"
    is_inferred: bool = False        # True = dérivé (YAML/LLM), pas trouvé verbatim dans l'AO
    estimated_score: int = 0         # rempli par step4
    risk_level: str = "MODÉRÉ"       # FAIBLE / MODÉRÉ / ÉLEVÉ / CRITIQUE
    rationale: str = ""              # justification du score estimé
    sources_ged: list[str] = field(default_factory=list)  # filenames GED contributifs


@dataclass
class Risk:
    """Un risque structuré avec sa mitigation obligatoire."""
    label: str                       # "Absence de livrables BI/Analytics"
    criticite: str = "MODÉRÉ"        # BLOQUANT / CRITIQUE / ÉLEVÉ / MODÉRÉ
    pourquoi: str = ""               # "20 pts de la grille dépendent de CVs concrets"
    mitigation: str = ""             # "Constituer GECA avec partenaire BI"
    items_affected: list[str] = field(default_factory=list)  # ids de critères liés


@dataclass
class Precondition:
    """Préalable conditionnant le passage CONDITIONAL → GO.

    Sert aussi de validation partenaire (étape 0 stratégie) : `pieces_requises`
    porte alors les justificatifs à fournir sur le partenaire de groupement.
    """
    label: str                       # "Confirmer CA ≥ 500 M FCFA"
    type: str = "ADMIN"              # FINANCIER / ADMIN / TECHNIQUE / PARTENARIAT
    deadline: str = ""               # date ISO ou "avant J-X"
    responsable: str = ""            # "Responsable Financier"
    status: str = "PENDING"
    blocking: bool = False           # True si non satisfait → NO_BID
    pieces_requises: list[str] = field(default_factory=list)  # justificatifs (ex: bilans 2023-2025)


@dataclass
class Appendix:
    """Pièce/annexe RÉELLE à fournir, extraite verbatim de l'AO (pas générique)."""
    code: str                        # "5A" / "Annexe 3" / "App. B"
    label: str                       # "Déclaration de conformité"
    type: str = "ADMIN"              # ADMIN / TECHNIQUE / FINANCIER / RH
    obligatoire: bool = True
    langue: str = ""                 # FR / EN / bilingue
    responsable: str = ""            # "Resp. Admin & Juridique"
    deadline_interne: str = ""       # avant la soumission
    statut: str = "PENDING"          # PENDING / EN_COURS / OK / NOK
    source_section: str = ""         # ex: "Section III Article 12"
    note: str = ""


@dataclass
class RequiredProfile:
    """Profil/ressource humaine demandé par l'AO, extrait verbatim avec TOUT son détail.

    Granularité maximale : pas « ingénieur » mais « Ingénieur Data, BAC+5, 5 ans,
    SQL/Python/Power BI, certifié Azure ». Chaque champ = uniquement ce que l'AO écrit
    (anti-hallucination : vide/0 si non précisé, jamais inventé)."""
    profil: str                      # intitulé EXACT ("Ingénieur Data", "Analyste C-SOC")
    domaine: str = ""                # spécialité ("Data/BI", "Cybersécurité", "Réseau")
    quantite: int = 0                # nombre de postes ; 0 si non précisé
    niveau: str = ""                 # "BAC+5", "Spécialiste", "Senior"
    experience_min: str = ""         # "5 ans", "2 à 4 ans en SOC"
    competences: list[str] = field(default_factory=list)      # compétences techniques exigées
    certifications: list[str] = field(default_factory=list)   # certifs exigées
    missions: list[str] = field(default_factory=list)         # responsabilités décrites par l'AO
    rattachement: str = ""           # division/service ("TCIS6")
    source_section: str = ""


@dataclass
class EligibilityThreshold:
    """Seuil CHIFFRÉ conditionnant la recevabilité (alimente la porte éliminatoire).

    Ex: CA ≥ 500M FCFA/an, 3 références, 5 ans d'expérience, caution 2%."""
    libelle: str                     # "Chiffre d'affaires annuel minimum"
    valeur: str = ""                 # "500 000 000" (verbatim — string pour garder format/unités)
    unite: str = ""                  # "FCFA/an", "références", "ans"
    type: str = "AUTRE"              # FINANCIER / EXPERIENCE / REFERENCES / ADMIN / AUTRE
    blocking: bool = True            # éliminatoire si non satisfait
    source_section: str = ""


@dataclass
class FinancialData:
    """Données financières chiffrées de l'AO (verbatim, vides si non communiquées)."""
    budget_estime: str = ""          # montant ou fourchette si donné
    modalites_paiement: str = ""     # "30% avance, 70% à 30j"
    garantie_soumission: str = ""    # caution / garantie de soumission
    penalites: str = ""              # pénalités de retard
    source_section: str = ""


@dataclass
class CapabilityDeal:
    """Une affaire Odoo retenue comme preuve de capacité (sans aucun montant)."""
    client: str
    title: str
    year: str = ""
    status: str = ""                 # Gagné / Perdu / En cours / …
    source: str = "opportunité"      # opportunité / commande


@dataclass
class CapabilityMatch:
    """Regroupement d'affaires Odoo prouvant une capacité demandée par l'AO.

    Produit par l'enrichissement (couches sémantique + LLM + garde-fou). AUCUN montant.
    """
    theme: str                       # libellé émergent ("Développement / personnalisation Odoo")
    confidence: str = "MOYENNE"      # FORTE / MOYENNE / FAIBLE
    is_critical: bool = False        # couvre un terme éliminatoire/critique (ex: FNE)
    won_count: int = 0               # nb d'affaires gagnées dans le groupe
    clients: list[str] = field(default_factory=list)
    deals: list[CapabilityDeal] = field(default_factory=list)


@dataclass
class ClientContext:
    """Contexte du donneur d'ordre issu d'Odoo (miroir SQLite local).

    Enrichissement du scoring. Règle stricte : AUCUN montant — uniquement des signaux
    RELATIONNELS, d'EXPÉRIENCE et de FIABILITÉ opérationnelle.
    """
    matched: bool = False
    odoo_client_name: str = ""
    match_confidence: str = ""            # EXACT / FORTE / FAIBLE
    # Identité
    city: str = ""
    country: str = ""
    known_contact: str = ""               # email ou téléphone connu
    # Relation
    is_existing_client: bool = False
    first_interaction: str = ""           # année de la 1re trace
    last_interaction: str = ""            # année de la dernière trace
    account_owner: str = ""               # commercial référent
    # Track record commercial — COMPTEURS et TAUX, jamais de montants
    opportunities_total: int = 0
    opportunities_won: int = 0
    opportunities_lost: int = 0
    win_rate_pct: int = 0                 # gagné / (gagné+perdu)
    open_opportunities: list[str] = field(default_factory=list)
    # Expérience de livraison
    orders_count: int = 0
    deployed_technologies: list[str] = field(default_factory=list)
    # Fiabilité opérationnelle (sans montants)
    invoices_total: int = 0
    invoices_paid: int = 0
    invoices_overdue: int = 0
    payment_reliability: str = ""         # BONNE / MOYENNE / À SURVEILLER / INCONNUE
    # Signaux dérivés
    relationship_signals: list[str] = field(default_factory=list)
    relationship_risks: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class ScoringResult:
    """Résultat complet du pipeline de scoring AO en 5 étapes."""
    ao_filename: str
    summary: str
    key_elements: list[KeyElement]
    matched_documents: list[MatchedDocument]
    gaps_analysis: str
    strengths: list[str]
    risks: list["Risk"]              # migration franche : était list[str]
    score: int
    recommendation: BidRecommendation
    justification: str
    # Base du score : "GRILLE" (somme normalisée d'un barème chiffré), "ESTIME" (jugement
    # global, AO sans barème), "INDISPONIBLE" (analyse cassée/tronquée → 50 neutre, pas un vrai score).
    score_basis: str = "GRILLE"
    # Scores de préparation par volet (Phase 3 Bid Management) : technique = alias du score
    # global (la grille notée EST la grille technique) ; financier/administratif = jugement LLM
    # de notre capacité à satisfaire les seuils/pièces du volet, distinct du score global.
    score_technique: int = 0
    score_financier: int = 0
    score_administratif: int = 0
    financier_rationale: str = ""
    administratif_rationale: str = ""
    # Champs d'analyse détaillée (Phase 1 Bid Management). Enrichis : chaque item
    # porte sa référence source (ExtractedItem) → traçabilité jusqu'à la matrice.
    criteres_selection: list[ExtractedItem] = field(default_factory=list)
    besoins: list[ExtractedItem] = field(default_factory=list)
    prerequis: list[ExtractedItem] = field(default_factory=list)
    ressources_demandees: list[ExtractedItem] = field(default_factory=list)
    points_vigilance: list[ExtractedItem] = field(default_factory=list)
    date_remise: str = ""
    # Matching GED automatique (Step 3 pipeline)
    team_matches: list[MatchedDocument] = field(default_factory=list)
    similar_projects: list[MatchedDocument] = field(default_factory=list)
    # Analyse AO standardisée — Fiche d'identité + Calendrier + Évaluation
    market_identity: MarketIdentity = field(default_factory=MarketIdentity)
    calendar: list[CalendarEvent] = field(default_factory=list)
    evaluation_modalities: EvaluationModalities = field(default_factory=EvaluationModalities)
    # Décomposition du score (Phase 2 Bid Management)
    criteria_breakdown: list[ScoringCriterion] = field(default_factory=list)
    preconditions: list[Precondition] = field(default_factory=list)  # rempli si CONDITIONAL
    preconditions_incomplete: bool = False  # True = CONDITIONAL sans préalables (dégradation)
    # Pièces/annexes à fournir, extraites verbatim de l'AO (alimente la checklist & la stratégie)
    appendices: list[Appendix] = field(default_factory=list)
    appendices_incomplete: bool = False  # True = aucune annexe trouvée dans l'AO (à clarifier)
    # Exigences CHIFFRÉES extraites verbatim (cœur de valeur métier) — étape 1b-exigences
    profils_demandes: list[RequiredProfile] = field(default_factory=list)
    seuils_eligibilite: list[EligibilityThreshold] = field(default_factory=list)
    donnees_financieres: FinancialData = field(default_factory=FinancialData)
    # Enrichissement Odoo (étape 6, non-bloquante) — miroir SQLite, sans montants
    client_context: ClientContext = field(default_factory=ClientContext)
    capability_matches: list[CapabilityMatch] = field(default_factory=list)
    capability_gaps: list[str] = field(default_factory=list)  # capacités exigées sans preuve Odoo


@dataclass
class Partner:
    """Partenaire de groupement (GECA, consortium, sous-traitant)."""
    name: str
    role: str = "membre_groupement"  # chef_de_file / membre_groupement / sous_traitant
    type: str = "entreprise"         # entreprise / consortium


@dataclass
class PhaseAction:
    """Une action concrète dans une phase du plan de réponse."""
    day_label: str                   # "Lundi 4 mai" ou "J1" si dates non calées
    action: str                      # "Kick-off interne et attribution des rôles"
    responsable: str = ""            # rôle dans la whitelist des acteurs Neurones
    duree_estimee: str = ""          # "2h"
    deliverable: str = ""            # ce qui sort (ex: "PV de réunion signé")
    statut: str = "PENDING"          # PENDING / IN_PROGRESS / DONE


@dataclass
class StrategyPhase:
    """Une phase du plan de réponse (5 en standard, 3 en express)."""
    id: str                          # "PHASE_0" / "PHASE_1" / ...
    name: str                        # "Go/No-Go GECA"
    description: str = ""
    start_day: str = ""              # "J1" ou date ISO
    end_day: str = ""
    actions: list[PhaseAction] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)  # ids des phases bloquantes
    is_blocking_next: bool = False   # True si cette phase bloque la suivante tant que non DONE


@dataclass
class BidStrategy:
    """Plan de réponse structuré — remplace le dict {strategy, chronogram, response_plan}."""
    phases: list[StrategyPhase] = field(default_factory=list)
    strategy_text: str = ""          # 5 paragraphes (conservé)
    response_plan: str = ""          # 4 paragraphes (conservé)
    appendices: list[Appendix] = field(default_factory=list)
    partner: Partner | None = None
    # Validation partenaire (étape 0) — réutilise Precondition (pas de structure dupliquée)
    partner_validation: list[Precondition] = field(default_factory=list)
    version: int = 1
    parent_version: int | None = None
    generated_at: str = ""


@dataclass
class RFP:
    """Appel d'Offres uploadé par l'utilisateur."""
    filename: str
    content: str
    file_type: str


@dataclass
class OfferDraft:
    """Offre technique générée."""
    filename: str
    content_docx: bytes
    ao_filename: str
    sections: list[str] = field(default_factory=list)
