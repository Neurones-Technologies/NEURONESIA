"""
Extraction automatique de métadonnées structurées à l'ingestion.

Utilise Claude Haiku via tool_use pour forcer une sortie JSON schématisée par doc_type.
Le LLM est contraint à appeler l'outil → pas de parsing de texte libre, pas de risque de format invalide.
Le texte est tronqué à 3 000 caractères pour maîtriser le coût API.
"""
import logging

from core.domain.document import DocumentType
from core.ports.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

_TEXT_LIMIT = 3000

_SYSTEM_PROMPT = (
    "Tu es un extracteur de métadonnées documentaires. "
    "Lis le document et appelle OBLIGATOIREMENT l'outil fourni avec les informations extraites. "
    "Si une information est absente du texte, utilise null. "
    "Ne génère AUCUN texte libre, seulement l'appel d'outil."
)

# ── Schémas de tools par type ────────────────────────────────────────────────

_TOOLS: dict[DocumentType, dict] = {
    DocumentType.CV: {
        "name": "extract_cv_metadata",
        "description": "Extraire les métadonnées d'un CV d'ingénieur",
        "input_schema": {
            "type": "object",
            "properties": {
                "nom": {"type": "string", "description": "Nom complet de la personne"},
                "role": {"type": "string", "description": "Poste / titre professionnel actuel"},
                "experience_years": {"type": "integer", "description": "Années d'expérience totale"},
                "skills": {"type": "array", "items": {"type": "string"}, "description": "Compétences techniques"},
                "certifications": {"type": "array", "items": {"type": "string"}, "description": "Certifications obtenues"},
                "diplomes": {"type": "array", "items": {"type": "string"}, "description": "Diplômes"},
                "langues": {"type": "array", "items": {"type": "string"}, "description": "Langues parlées"},
            },
            "required": ["nom", "role", "experience_years", "skills"],
        },
    },
    DocumentType.AO: {
        "name": "extract_ao_metadata",
        "description": "Extraire les métadonnées d'un appel d'offres",
        "input_schema": {
            "type": "object",
            "properties": {
                "client": {"type": "string", "description": "Nom du client / commanditaire"},
                "secteur": {"type": "string", "description": "Secteur d'activité"},
                "budget_estime": {"type": "string", "description": "Budget estimé (avec unité)"},
                "date_limite": {"type": "string", "description": "Date limite de soumission (ISO 8601)"},
                "statut_ao": {
                    "type": "string",
                    "enum": ["a_traiter", "en_cours", "soumis"],
                    "description": "Statut de traitement de l'AO",
                },
            },
            "required": ["client"],
        },
    },
    DocumentType.ABE: {
        "name": "extract_abe_metadata",
        "description": "Extraire les métadonnées d'un marché public ABE",
        "input_schema": {
            "type": "object",
            "properties": {
                "client": {"type": "string"},
                "secteur": {"type": "string"},
                "budget_estime": {"type": "string"},
                "date_limite": {"type": "string"},
                "reference": {"type": "string", "description": "Référence du marché"},
            },
            "required": ["client"],
        },
    },
    DocumentType.OFFRE_TECHNIQUE: {
        "name": "extract_offre_metadata",
        "description": "Extraire les métadonnées d'une offre technique soumise",
        "input_schema": {
            "type": "object",
            "properties": {
                "titre": {"type": "string", "description": "Titre du projet / de l'offre"},
                "client": {"type": "string"},
                "secteur": {"type": "string"},
                "montant": {"type": "string", "description": "Montant de l'offre (avec unité)"},
                "statut_gagne": {"type": "boolean", "description": "Offre gagnée (true) ou perdue (false)"},
            },
            "required": ["titre", "client"],
        },
    },
    DocumentType.FICHE_TECHNIQUE: {
        "name": "extract_fiche_metadata",
        "description": "Extraire les métadonnées d'une fiche technique produit",
        "input_schema": {
            "type": "object",
            "properties": {
                "reference_produit": {"type": "string", "description": "Référence / code produit"},
                "gamme": {"type": "string", "description": "Gamme de produit"},
                "famille": {"type": "string", "description": "Famille de produit"},
                "fabricant": {"type": "string"},
            },
            "required": ["reference_produit"],
        },
    },
    DocumentType.PROCEDURE: {
        "name": "extract_procedure_metadata",
        "description": "Extraire les métadonnées d'une procédure interne",
        "input_schema": {
            "type": "object",
            "properties": {
                "code_procedure": {"type": "string", "description": "Code unique de la procédure"},
                "titre": {"type": "string"},
                "version": {"type": "string"},
                "statut_vigueur": {
                    "type": "string",
                    "enum": ["en_vigueur", "archivee"],
                    "description": "Statut de la procédure",
                },
                "domaine": {"type": "string", "description": "Domaine ou service concerné"},
            },
            "required": ["code_procedure", "titre"],
        },
    },
    DocumentType.PV_RECETTE: {
        "name": "extract_pv_metadata",
        "description": "Extraire les métadonnées d'un PV de recette ou compte-rendu",
        "input_schema": {
            "type": "object",
            "properties": {
                "date_reunion": {"type": "string", "description": "Date de la réunion (ISO 8601)"},
                "projet_id": {"type": "string"},
                "participants": {"type": "array", "items": {"type": "string"}},
                "decisions": {"type": "array", "items": {"type": "string"}, "description": "Décisions prises"},
                "actions": {"type": "array", "items": {"type": "string"}, "description": "Actions à réaliser"},
            },
            "required": ["date_reunion"],
        },
    },
    DocumentType.COMPTE_RENDU: {
        "name": "extract_cr_metadata",
        "description": "Extraire les métadonnées d'un compte-rendu de réunion",
        "input_schema": {
            "type": "object",
            "properties": {
                "date_reunion": {"type": "string"},
                "projet_id": {"type": "string"},
                "participants": {"type": "array", "items": {"type": "string"}},
                "decisions": {"type": "array", "items": {"type": "string"}},
                "actions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["date_reunion"],
        },
    },
}


class MetadataExtractor:
    def __init__(self, llm: LLMGateway):
        self._llm = llm

    async def extract(self, text: str, doc_type: DocumentType) -> dict:
        """
        Retourne un dict des champs extraits, ou {} si le type n'a pas de schéma
        ou si l'extraction échoue.
        """
        tool_def = _TOOLS.get(doc_type)
        if tool_def is None:
            return {}

        try:
            result = await self._llm.agentic_step(
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text[:_TEXT_LIMIT]}],
                tools=[tool_def],
                max_tokens=512,
            )
            if result.tool_calls:
                return result.tool_calls[0].get("input", {})
            logger.warning("MetadataExtractor : aucun tool_call pour %s", doc_type.value)
            return {}
        except Exception as exc:
            logger.warning("MetadataExtractor échoué pour %s : %s", doc_type.value, exc)
            return {}
