"""
Schémas d'extraction typés (Pydantic v2) — un modèle par type de document.

Reflètent les 6 schémas du playbook §3, mais normalisés :
- chaque montant → un objet `Montant(valeur: float|None, devise: str)` ;
- chaque date → `datetime` (ou None) via `parse_date`.

Ces modèles VALIDENT la sortie `tool_use` du LLM avant toute persistance.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from core.domain.document import DocumentType
from core.services.extraction.normalizers import (
    DEFAULT_DEVISE,
    detect_devise,
    parse_date,
    parse_montant,
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


# Type date tolérant : accepte str ISO/FR, datetime, ou None.
OptDate = Annotated[Optional[datetime], BeforeValidator(parse_date)]


class Montant(_Base):
    """Montant normalisé : valeur numérique + devise canonique (XOF par défaut)."""
    valeur: Optional[float] = None
    devise: str = DEFAULT_DEVISE

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data):
        if data is None:
            return {"valeur": None, "devise": DEFAULT_DEVISE}
        if isinstance(data, (int, float)):
            return {"valeur": float(data), "devise": DEFAULT_DEVISE}
        if isinstance(data, str):
            valeur, devise = parse_montant(data)
            return {"valeur": valeur, "devise": devise}
        if isinstance(data, dict):
            raw = data.get("valeur", data.get("montant"))
            dev = data.get("devise")
            devise = detect_devise(dev, DEFAULT_DEVISE) if dev else None
            if isinstance(raw, str):
                valeur, detected = parse_montant(raw)
                return {"valeur": valeur, "devise": devise or detected}
            return {
                "valeur": float(raw) if isinstance(raw, (int, float)) else None,
                "devise": devise or DEFAULT_DEVISE,
            }
        return data


# ── 3.1 CV ───────────────────────────────────────────────────────────────────

class Langue(_Base):
    langue: Optional[str] = None
    niveau: Optional[str] = None


class Competence(_Base):
    libelle: Optional[str] = None
    categorie: Optional[str] = None
    niveau: Optional[str] = None


class CertifCitee(_Base):
    intitule: Optional[str] = None
    organisme: Optional[str] = None
    annee: Optional[int] = None


class Experience(_Base):
    intitule_projet: Optional[str] = None
    client: Optional[str] = None
    role: Optional[str] = None
    secteur: Optional[str] = None
    date_debut: OptDate = None
    date_fin: OptDate = None
    en_cours: bool = False
    description_courte: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _flag_en_cours(cls, data):
        if isinstance(data, dict):
            fin = data.get("date_fin")
            if isinstance(fin, str) and "cours" in fin.lower():
                data = {**data, "en_cours": True}
        return data


class Formation(_Base):
    diplome: Optional[str] = None
    etablissement: Optional[str] = None
    annee: Optional[int] = None


class Personne(_Base):
    nom_complet: Optional[str] = None
    titre_poste: Optional[str] = None
    annees_experience_total: Optional[float] = None
    localisation: Optional[str] = None


class CVExtraction(_Base):
    type: str = "cv"
    personne: Personne = Field(default_factory=Personne)
    langues: List[Langue] = Field(default_factory=list)
    competences: List[Competence] = Field(default_factory=list)
    certifications_citees: List[CertifCitee] = Field(default_factory=list)
    experiences: List[Experience] = Field(default_factory=list)
    formations: List[Formation] = Field(default_factory=list)
    secteurs_expertise: List[str] = Field(default_factory=list)


# ── 3.2 Appel d'offres ───────────────────────────────────────────────────────

class Lot(_Base):
    numero: Optional[str] = None
    intitule: Optional[str] = None
    montant_estime: Optional[Montant] = None


class Exigence(_Base):
    categorie: Optional[str] = None
    libelle: Optional[str] = None
    obligatoire: bool = True


class ReferenceDemandee(_Base):
    description: Optional[str] = None
    nombre_min: Optional[int] = None
    montant_min: Optional[Montant] = None
    periode: Optional[str] = None


class CritereEvaluation(_Base):
    critere: Optional[str] = None
    ponderation: Optional[float] = None


class AOExtraction(_Base):
    type: str = "appel_offres"
    reference: Optional[str] = None
    intitule: Optional[str] = None
    maitre_ouvrage: Optional[str] = None
    date_publication: OptDate = None
    date_limite_remise: OptDate = None
    budget_estime: Optional[Montant] = None
    type_marche: Optional[str] = None
    duree_execution: Optional[str] = None
    lots: List[Lot] = Field(default_factory=list)
    exigences_obligatoires: List[Exigence] = Field(default_factory=list)
    references_demandees: List[ReferenceDemandee] = Field(default_factory=list)
    certifications_exigees: List[str] = Field(default_factory=list)
    criteres_evaluation: List[CritereEvaluation] = Field(default_factory=list)


# ── 3.3 Compte rendu ─────────────────────────────────────────────────────────

class Participant(_Base):
    nom: Optional[str] = None
    organisation: Optional[str] = None
    role: Optional[str] = None


class Action(_Base):
    libelle: Optional[str] = None
    responsable: Optional[str] = None
    echeance: OptDate = None
    statut: Optional[str] = None


class CompteRenduExtraction(_Base):
    type: str = "compte_rendu"
    date_reunion: OptDate = None
    objet: Optional[str] = None
    projet_associe: Optional[str] = None
    lieu: Optional[str] = None
    participants: List[Participant] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    actions: List[Action] = Field(default_factory=list)
    points_abordes: List[str] = Field(default_factory=list)


# ── 3.4 Certification ────────────────────────────────────────────────────────

class CertificationExtraction(_Base):
    type: str = "certification"
    titulaire: Optional[str] = None
    intitule: Optional[str] = None
    organisme_emetteur: Optional[str] = None
    numero_identifiant: Optional[str] = None
    date_emission: OptDate = None
    date_expiration: OptDate = None
    statut: Optional[str] = None
    domaine: Optional[str] = None


# ── 3.5 PV de recette ────────────────────────────────────────────────────────

class Livrable(_Base):
    intitule: Optional[str] = None
    statut: Optional[str] = None


class Reserve(_Base):
    description: Optional[str] = None
    criticite: Optional[str] = None
    statut: Optional[str] = None
    date_levee: OptDate = None


class Signataire(_Base):
    nom: Optional[str] = None
    fonction: Optional[str] = None
    organisation: Optional[str] = None


class PVRecetteExtraction(_Base):
    type: str = "pv_recette"
    reference: Optional[str] = None
    projet_associe: Optional[str] = None
    client: Optional[str] = None
    date: OptDate = None
    type_recette: Optional[str] = None
    livrables: List[Livrable] = Field(default_factory=list)
    statut_global: Optional[str] = None
    reserves: List[Reserve] = Field(default_factory=list)
    signataires: List[Signataire] = Field(default_factory=list)


# ── 3.6 Attestation de bonne exécution ───────────────────────────────────────

class ABEExtraction(_Base):
    type: str = "attestation_bonne_execution"
    reference: Optional[str] = None
    emetteur_client: Optional[str] = None
    projet_marche: Optional[str] = None
    perimetre_prestations: List[str] = Field(default_factory=list)
    montant: Optional[Montant] = None
    date_debut: OptDate = None
    date_fin: OptDate = None
    duree_mois: Optional[int] = None
    niveau_appreciation: Optional[str] = None
    signataire: Optional[Signataire] = None
    secteur: Optional[str] = None


# ── Registre type de document → modèle ───────────────────────────────────────

CONTENT_MODELS: dict[DocumentType, type[_Base]] = {
    DocumentType.CV: CVExtraction,
    DocumentType.AO: AOExtraction,
    DocumentType.COMPTE_RENDU: CompteRenduExtraction,
    DocumentType.CERTIFICATION: CertificationExtraction,
    DocumentType.PV_RECETTE: PVRecetteExtraction,
    DocumentType.ABE: ABEExtraction,
}
