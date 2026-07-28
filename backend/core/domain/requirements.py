"""
Source de vérité UNIQUE de la conformité (UC10 Pre-Sales).

Une exigence d'AO = UN objet `Exigence` : texte extrait, référence dans le
document source, domaine(s) technique(s), section de réponse, statut de
conformité, commentaire. La matrice de conformité Excel et — à terme — le
mémoire technique Word sont des VUES générées depuis ce schéma, jamais des
sources de données concurrentes.

Décisions actées (cf. contexte projet) :
- DOMAINE = TAG MULTI-VALEUR : une exigence peut relever de plusieurs domaines
  (`domaines_suggeres`). On ne force jamais un domaine unique ni ne duplique
  l'exigence par domaine.
- CLASSIFICATION EN 2 CHAMPS : `domaines_suggeres` (sortie du classifieur) +
  `domaine_valide` (corrigé humain), pour mesurer la précision dans le temps.
- EXHAUSTIVITÉ : la consolidation ne perd aucune exigence (une exigence oubliée
  = offre éliminée). `MatriceConformite` porte le compte et les statistiques.

Ce module ne dépend QUE de la stdlib : c'est du domaine pur, sérialisable JSON
en round-trip (dataclasses → dict → json et retour), testé.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

# ── Vocabulaires contrôlés ──────────────────────────────────────────────────
# Domaine sentinelle quand le classifieur ne reconnaît rien (jamais de perte :
# l'exigence reste dans la matrice, signalée « à classer »).
DOMAINE_NON_CLASSE = "Non classé"

# Type métier de l'exigence = champ de `ScoringResult` dont elle est issue.
# Sert au regroupement dans la matrice et à tracer l'origine (pas de perte).
TYPE_BESOIN = "BESOIN"
TYPE_CRITERE = "CRITERE"
TYPE_PREREQUIS = "PREREQUIS"
TYPE_RESSOURCE = "RESSOURCE"
TYPE_VIGILANCE = "VIGILANCE"
TYPE_PROFIL = "PROFIL"
TYPE_SEUIL = "SEUIL"
TYPE_ANNEXE = "ANNEXE"
TYPE_GRILLE = "GRILLE"
TYPES_EXIGENCE = frozenset({
    TYPE_BESOIN, TYPE_CRITERE, TYPE_PREREQUIS, TYPE_RESSOURCE, TYPE_VIGILANCE,
    TYPE_PROFIL, TYPE_SEUIL, TYPE_ANNEXE, TYPE_GRILLE,
})

# Statut de conformité = avancement du traitement de l'exigence dans l'offre.
STATUT_A_TRAITER = "A_TRAITER"
STATUT_CONFORME = "CONFORME"
STATUT_CONFORME_PARTIEL = "CONFORME_PARTIEL"
STATUT_NON_CONFORME = "NON_CONFORME"
STATUT_NON_APPLICABLE = "NON_APPLICABLE"
STATUTS_CONFORMITE = frozenset({
    STATUT_A_TRAITER, STATUT_CONFORME, STATUT_CONFORME_PARTIEL,
    STATUT_NON_CONFORME, STATUT_NON_APPLICABLE,
})


@dataclass
class Exigence:
    """Une exigence d'AO — unité atomique de la matrice de conformité.

    Anti-hallucination : `texte` et `source_ref` sont repris VERBATIM de l'AO ;
    on n'invente jamais une exigence ni une référence. `domaines_suggeres` est
    le seul champ « calculé » (par le classifieur) ; `domaine_valide` reste vide
    tant qu'un humain ne l'a pas corrigé.
    """
    id: str                                  # identifiant stable dans la matrice (ex: "EX-0001")
    texte: str                               # libellé de l'exigence, verbatim
    source_ref: str = ""                     # référence dans l'AO (section/article/page) — "" si inconnue
    type: str = TYPE_BESOIN                  # cf. TYPES_EXIGENCE — champ source d'origine
    origine: str = ""                        # champ exact de ScoringResult (ex: "besoins", "profils_demandes")
    domaines_suggeres: list[str] = field(default_factory=list)  # multi-valeur (sortie classifieur)
    domaine_valide: str = ""                 # corrigé humain (vide = pas encore validé)
    confidence: float = 0.0                  # confiance du classifieur (0.0–1.0)
    section_reponse: str = ""                # section de l'offre qui couvre l'exigence
    statut_conformite: str = STATUT_A_TRAITER  # statut VALIDÉ par l'humain (cochage) — cf. STATUTS_CONFORMITE
    blocking: bool = False                   # éliminatoire si non couverte (seuils, pièces obligatoires)
    commentaire: str = ""
    # ── Validation IA → contrôle humain ────────────────────────────────────────
    # Modèle « suggéré par l'IA → confirmé par l'humain », calqué sur
    # domaines_suggeres → domaine_valide. L'IA propose `statut_suggere` (+ justification,
    # confiance, preuve) ; l'humain COCHE pour confirmer (`confirme=True`) en fixant
    # `statut_conformite`. Tant que non confirmé, `statut_conformite` reste A_TRAITER :
    # on ne considère JAMAIS une exigence « réunie » sur la seule foi de l'IA.
    statut_suggere: str = STATUT_A_TRAITER   # proposition IA (cf. STATUTS_CONFORMITE)
    justification_ia: str = ""               # pourquoi l'IA propose ce statut (traçable)
    confiance_ia: float = 0.0                # 0.0–1.0
    preuve_ref: str = ""                     # pointeur de preuve (critère, doc GED, force)
    confirme: bool = False                   # True = un humain a coché pour confirmer
    confirme_par: str = ""                   # email/nom du valideur humain
    confirme_le: str = ""                    # ISO 8601, posé à la confirmation

    def __post_init__(self) -> None:
        # Normalisation défensive : un type/statut hors vocabulaire est ramené à
        # une valeur sûre plutôt que de propager une donnée invalide dans la matrice.
        if self.type not in TYPES_EXIGENCE:
            self.type = TYPE_BESOIN
        if self.statut_conformite not in STATUTS_CONFORMITE:
            self.statut_conformite = STATUT_A_TRAITER
        if self.statut_suggere not in STATUTS_CONFORMITE:
            self.statut_suggere = STATUT_A_TRAITER

    @property
    def domaine_effectif(self) -> str:
        """Domaine retenu pour les vues : le validé s'il existe, sinon le 1er suggéré.

        Permet de générer une vue mono-domaine (ex: regroupement Excel) sans
        écraser l'information multi-valeur conservée dans `domaines_suggeres`.
        """
        if self.domaine_valide:
            return self.domaine_valide
        return self.domaines_suggeres[0] if self.domaines_suggeres else DOMAINE_NON_CLASSE

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Exigence":
        """Reconstruit une Exigence depuis un dict (tolère les champs absents/en trop)."""
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class MatriceConformite:
    """Conteneur des exigences d'un AO — la matrice de conformité.

    Porte la garantie d'EXHAUSTIVITÉ : `total` = nombre d'exigences consolidées.
    `expected_total`, renseigné par le builder, permet de vérifier qu'aucune
    exigence n'a été perdue entre l'extraction et la consolidation.
    """
    ao_filename: str
    exigences: list[Exigence] = field(default_factory=list)
    generated_at: str = ""                   # ISO 8601 (passé par l'appelant, pas de Date interne)
    expected_total: int | None = None        # nb d'items source attendus (contrôle d'exhaustivité)

    @property
    def total(self) -> int:
        return len(self.exigences)

    @property
    def is_exhaustive(self) -> bool:
        """True si le nombre d'exigences correspond à l'attendu (ou attendu non renseigné)."""
        return self.expected_total is None or self.total == self.expected_total

    def count_by_domaine(self) -> dict[str, int]:
        """Répartition par domaine effectif. Une exigence multi-domaine compte
        une fois par domaine suggéré (vue d'usage : « combien d'exigences Cloud »)."""
        counts: dict[str, int] = {}
        for ex in self.exigences:
            domaines = [ex.domaine_valide] if ex.domaine_valide else (ex.domaines_suggeres or [DOMAINE_NON_CLASSE])
            for d in domaines:
                counts[d] = counts.get(d, 0) + 1
        return counts

    def count_by_statut(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for ex in self.exigences:
            counts[ex.statut_conformite] = counts.get(ex.statut_conformite, 0) + 1
        return counts

    def count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for ex in self.exigences:
            counts[ex.type] = counts.get(ex.type, 0) + 1
        return counts

    def to_dict(self) -> dict:
        return {
            "ao_filename": self.ao_filename,
            "exigences": [ex.to_dict() for ex in self.exigences],
            "generated_at": self.generated_at,
            "expected_total": self.expected_total,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MatriceConformite":
        return cls(
            ao_filename=str(data.get("ao_filename", "")),
            exigences=[Exigence.from_dict(e) for e in data.get("exigences", []) if isinstance(e, dict)],
            generated_at=str(data.get("generated_at", "")),
            expected_total=data.get("expected_total"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "MatriceConformite":
        return cls.from_dict(json.loads(raw))
