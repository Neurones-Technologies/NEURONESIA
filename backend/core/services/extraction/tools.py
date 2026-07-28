"""
Définitions d'outils Anthropic (`tool_use`) pour l'extraction structurée.

Les noms de propriétés sont alignés sur les champs des modèles Pydantic
(`schemas.py`) afin que la sortie de l'outil soit validable directement par
`model_validate`. Les montants sont demandés sous forme `{ "valeur", "devise" }`
ou nombre ; la normalisation finale est faite par les modèles Pydantic.
"""
from __future__ import annotations

from core.domain.document import DocumentType

_STR = {"type": "string"}
_NULLABLE_STR = {"type": ["string", "null"]}


def _montant_obj(desc: str = "Montant") -> dict:
    return {
        "type": "object",
        "description": f"{desc} : valeur numérique brute + devise (FCFA/XOF, EUR, USD…)",
        "properties": {
            "valeur": {"type": ["number", "string", "null"]},
            "devise": {"type": ["string", "null"]},
        },
    }


_CV_TOOL = {
    "name": "extract_cv",
    "description": "Extraire les données structurées d'un CV d'ingénieur/consultant.",
    "input_schema": {
        "type": "object",
        "properties": {
            "personne": {
                "type": "object",
                "properties": {
                    "nom_complet": _STR,
                    "titre_poste": _STR,
                    "annees_experience_total": {"type": ["number", "null"]},
                    "localisation": _NULLABLE_STR,
                },
            },
            "langues": {
                "type": "array",
                "items": {"type": "object", "properties": {"langue": _STR, "niveau": _STR}},
            },
            "competences": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "libelle": _STR, "categorie": _NULLABLE_STR, "niveau": _NULLABLE_STR}},
            },
            "certifications_citees": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "intitule": _STR, "organisme": _NULLABLE_STR, "annee": {"type": ["integer", "null"]}}},
            },
            "experiences": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "intitule_projet": _STR, "client": _STR, "role": _STR, "secteur": _STR,
                    "date_debut": {"type": ["string", "null"], "description": "AAAA-MM ou date"},
                    "date_fin": {"type": ["string", "null"], "description": "AAAA-MM, date, ou 'en cours'"},
                    "description_courte": _STR}},
            },
            "formations": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "diplome": _STR, "etablissement": _STR, "annee": {"type": ["integer", "null"]}}},
            },
            "secteurs_expertise": {"type": "array", "items": _STR},
        },
        "required": ["personne"],
    },
}

_AO_TOOL = {
    "name": "extract_appel_offres",
    "description": "Extraire les données structurées d'un appel d'offres.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reference": _STR,
            "intitule": _STR,
            "maitre_ouvrage": _STR,
            "date_publication": {"type": ["string", "null"], "description": "AAAA-MM-JJ"},
            "date_limite_remise": {"type": ["string", "null"], "description": "AAAA-MM-JJ"},
            "budget_estime": _montant_obj("Budget estimé"),
            "type_marche": _STR,
            "duree_execution": _NULLABLE_STR,
            "lots": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "numero": _STR, "intitule": _STR, "montant_estime": _montant_obj("Montant estimé du lot")}},
            },
            "exigences_obligatoires": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "categorie": {"type": "string",
                                  "enum": ["administrative", "technique", "financiere", "reference", "certification"]},
                    "libelle": _STR, "obligatoire": {"type": "boolean"}}},
            },
            "references_demandees": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "description": _STR, "nombre_min": {"type": ["integer", "null"]},
                    "montant_min": _montant_obj("Montant minimum demandé"), "periode": _NULLABLE_STR}},
            },
            "certifications_exigees": {"type": "array", "items": _STR},
            "criteres_evaluation": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "critere": _STR, "ponderation": {"type": ["number", "null"]}}},
            },
        },
        "required": ["intitule"],
    },
}

_CR_TOOL = {
    "name": "extract_compte_rendu",
    "description": "Extraire les données structurées d'un compte rendu de réunion.",
    "input_schema": {
        "type": "object",
        "properties": {
            "date_reunion": {"type": ["string", "null"], "description": "AAAA-MM-JJ"},
            "objet": _STR,
            "projet_associe": _NULLABLE_STR,
            "lieu": _NULLABLE_STR,
            "participants": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "nom": _STR, "organisation": _NULLABLE_STR, "role": _NULLABLE_STR}},
            },
            "decisions": {"type": "array", "items": _STR},
            "actions": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "libelle": _STR, "responsable": _STR,
                    "echeance": {"type": ["string", "null"]}, "statut": _STR}},
            },
            "points_abordes": {"type": "array", "items": _STR},
        },
        "required": ["date_reunion"],
    },
}

_CERTIF_TOOL = {
    "name": "extract_certification",
    "description": "Extraire les données structurées d'une certification.",
    "input_schema": {
        "type": "object",
        "properties": {
            "titulaire": _STR,
            "intitule": _STR,
            "organisme_emetteur": _STR,
            "numero_identifiant": _NULLABLE_STR,
            "date_emission": {"type": ["string", "null"], "description": "AAAA-MM-JJ"},
            "date_expiration": {"type": ["string", "null"], "description": "AAAA-MM-JJ"},
            "statut": {"type": "string", "enum": ["valide", "expiree", "inconnu"]},
            "domaine": _NULLABLE_STR,
        },
        "required": ["titulaire", "intitule", "organisme_emetteur"],
    },
}

_PV_TOOL = {
    "name": "extract_pv_recette",
    "description": "Extraire les données structurées d'un PV de recette.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reference": _STR,
            "projet_associe": _STR,
            "client": _STR,
            "date": {"type": ["string", "null"], "description": "AAAA-MM-JJ"},
            "type_recette": {"type": "string", "enum": ["provisoire", "definitive", "partielle"]},
            "livrables": {
                "type": "array",
                "items": {"type": "object", "properties": {"intitule": _STR, "statut": _STR}},
            },
            "statut_global": {"type": "string",
                              "enum": ["accepte", "accepte_avec_reserves", "refuse"]},
            "reserves": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "description": _STR,
                    "criticite": {"type": "string", "enum": ["mineure", "majeure", "bloquante"]},
                    "statut": {"type": "string", "enum": ["ouverte", "levee"]},
                    "date_levee": {"type": ["string", "null"]}}},
            },
            "signataires": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "nom": _STR, "fonction": _STR, "organisation": _STR}},
            },
        },
        "required": ["projet_associe"],
    },
}

_ABE_TOOL = {
    "name": "extract_attestation_bonne_execution",
    "description": "Extraire les données structurées d'une attestation de bonne exécution.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reference": _NULLABLE_STR,
            "emetteur_client": _STR,
            "projet_marche": _STR,
            "perimetre_prestations": {"type": "array", "items": _STR},
            "montant": _montant_obj("Montant du marché"),
            "date_debut": {"type": ["string", "null"], "description": "AAAA-MM-JJ"},
            "date_fin": {"type": ["string", "null"], "description": "AAAA-MM-JJ"},
            "duree_mois": {"type": ["integer", "null"]},
            "niveau_appreciation": _STR,
            "signataire": {"type": "object", "properties": {"nom": _STR, "fonction": _STR}},
            "secteur": _NULLABLE_STR,
        },
        "required": ["emetteur_client", "projet_marche"],
    },
}

TOOLS: dict[DocumentType, dict] = {
    DocumentType.CV: _CV_TOOL,
    DocumentType.AO: _AO_TOOL,
    DocumentType.COMPTE_RENDU: _CR_TOOL,
    DocumentType.CERTIFICATION: _CERTIF_TOOL,
    DocumentType.PV_RECETTE: _PV_TOOL,
    DocumentType.ABE: _ABE_TOOL,
}
