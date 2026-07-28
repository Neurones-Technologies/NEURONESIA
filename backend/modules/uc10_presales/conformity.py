"""
Pré-validation de conformité par l'IA (UC10 Pre-Sales).

But produit : « Validation de la checklist par l'IA, puis contrôle humain par
cochage confirmant que les éléments validés sont effectivement réunis. »

PRINCIPE — pas de nouvel appel LLM ici (donc aucun surcoût de latence) : on DÉRIVE
un statut suggéré par exigence à partir de l'analyse DÉJÀ produite par le pipeline
de scoring (grille `criteria_breakdown`, `strengths`, `risks`, `gaps_analysis`,
`capability_*`, `team_matches`). C'est déterministe, traçable (justification +
référence de preuve) et reproductible.

L'IA REMPLIT seulement `statut_suggere` / `justification_ia` / `confiance_ia` /
`preuve_ref`. Elle ne touche JAMAIS `statut_conformite` : ce dernier n'est posé
qu'au cochage humain (cf. matrix_store.apply_confirmations). On ne déclare donc
jamais une exigence « réunie » sur la seule foi de l'IA.

Module pur (stdlib + domaine) → testable hors réseau.
"""
from __future__ import annotations

import re
import unicodedata

from core.domain.offer import ScoringResult
from core.domain.requirements import (
    MatriceConformite, Exigence,
    STATUT_A_TRAITER, STATUT_CONFORME, STATUT_CONFORME_PARTIEL, STATUT_NON_CONFORME,
    TYPE_CRITERE, TYPE_PROFIL, TYPE_SEUIL, TYPE_ANNEXE,
)

# Criticités de risque qui plafonnent un statut « conforme »
_RISK_HARD = {"CRITIQUE", "BLOQUANT"}
_RISK_SOFT = {"ÉLEVÉ", "ELEVE", "MODÉRÉ", "MODERE"}

_STOPWORDS = {
    "pour", "avec", "dans", "les", "des", "une", "aux", "par", "sur", "que", "qui",
    "est", "son", "ses", "leur", "the", "and", "de", "du", "la", "le", "et", "en",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


def _tokens(s: str) -> set[str]:
    """Mots significatifs (≥ 4 lettres, hors mots-vides) d'une chaîne, accent-insensible."""
    return {w for w in re.findall(r"[a-z0-9]+", _norm(s)) if len(w) >= 4 and w not in _STOPWORDS}


def _overlap(a: str, b: str) -> float:
    """Recouvrement lexical [0..1] entre deux textes (intersection / plus petit ensemble)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / min(len(ta), len(tb))


def _best_match(texte: str, candidates: list[tuple[str, object]], threshold: float) -> tuple[object, float] | None:
    """Meilleur candidat (label, payload) par recouvrement lexical avec `texte`."""
    best, best_score = None, 0.0
    for label, payload in candidates:
        sc = _overlap(texte, label)
        if sc > best_score:
            best, best_score = payload, sc
    if best is not None and best_score >= threshold:
        return best, best_score
    return None


def derive_suggested_status(ex: Exigence, scoring: ScoringResult) -> tuple[str, str, float, str]:
    """Statut de conformité SUGGÉRÉ pour une exigence, dérivé de l'analyse IA du scoring.

    Retourne (statut, justification, confiance 0..1, preuve_ref). Ordre de priorité :
    grille de notation (le plus spécifique) → risques/écarts (négatif) → forces (positif)
    → profils/seuils/annexes → défaut « à traiter ».
    """
    texte = ex.texte

    # 1) Critère mappé sur la grille de notation chiffrée (signal le plus fort).
    if ex.type == TYPE_CRITERE and scoring.criteria_breakdown:
        cands = [(c.label, c) for c in scoring.criteria_breakdown if c.label]
        hit = _best_match(texte, cands, threshold=0.34)
        if hit:
            c, score = hit
            ratio = c.estimated_score / c.max_points if c.max_points else 0.0
            crit = (c.risk_level or "").upper()
            preuve = f"Critère « {c.label} » : {c.estimated_score}/{c.max_points} estimés"
            just = (c.rationale or preuve).strip()
            if ratio >= 0.8 and crit not in _RISK_HARD:
                return STATUT_CONFORME, just, round(min(0.5 + score / 2, 0.9), 2), preuve
            if ratio >= 0.5:
                return STATUT_CONFORME_PARTIEL, just, round(0.4 + score / 3, 2), preuve
            return STATUT_NON_CONFORME, just, round(0.4 + score / 3, 2), preuve

    # 2) Écart de capacité explicite (Odoo) → non couvert.
    for gap in (scoring.capability_gaps or []):
        if _overlap(texte, gap) >= 0.4:
            return (STATUT_NON_CONFORME,
                    f"Capacité non prouvée dans l'historique : {gap}", 0.5, f"Écart : {gap}")

    # 3) Risque identifié recoupant l'exigence → conformité dégradée.
    risk_cands = [(r.label, r) for r in (scoring.risks or []) if r.label]
    rhit = _best_match(texte, risk_cands, threshold=0.4)
    if rhit:
        r, score = rhit
        crit = (r.criticite or "").upper()
        just = (r.pourquoi or r.label).strip()
        if crit in _RISK_HARD:
            return STATUT_NON_CONFORME, f"Risque {r.criticite} : {just}", 0.5, f"Risque : {r.label}"
        return STATUT_CONFORME_PARTIEL, f"Risque {r.criticite} : {just}", 0.45, f"Risque : {r.label}"

    # 4) Force de Neurones recoupant l'exigence → couverte.
    strengths = [(s, s) for s in (scoring.strengths or []) if s]
    shit = _best_match(texte, strengths, threshold=0.4)
    if shit:
        s, score = shit
        return STATUT_CONFORME, f"Atout identifié : {s}", round(0.4 + score / 3, 2), f"Force : {s[:60]}"

    # 5) Profil RH demandé : des CV pertinents ont-ils été trouvés en GED ?
    if ex.type == TYPE_PROFIL:
        if scoring.team_matches:
            ref = scoring.team_matches[0].filename
            return (STATUT_CONFORME_PARTIEL,
                    "Des CV pertinents existent en GED — à confirmer (disponibilité, adéquation).",
                    0.4, f"CV GED : {ref}")
        return (STATUT_A_TRAITER,
                "Aucun CV correspondant trouvé automatiquement — mobilisation RH à vérifier.", 0.2, "")

    # 6) Seuil éliminatoire / pièce obligatoire : vérification humaine indispensable.
    if ex.type in (TYPE_SEUIL, TYPE_ANNEXE) and ex.blocking:
        return (STATUT_A_TRAITER,
                "Élément éliminatoire : pièce/seuil à réunir et vérifier manuellement avant dépôt.",
                0.3, "")

    # 7) Par défaut : à évaluer par l'humain (l'IA n'a pas de signal fiable).
    return STATUT_A_TRAITER, "À évaluer manuellement (aucun signal IA fiable).", 0.0, ""


def assess_matrice(matrice: MatriceConformite, scoring: ScoringResult) -> MatriceConformite:
    """Renseigne le pré-statut IA de CHAQUE exigence (en place) et renvoie la matrice.

    Ne modifie pas `statut_conformite` (réservé au cochage humain). Idempotent.
    """
    for ex in matrice.exigences:
        statut, just, conf, preuve = derive_suggested_status(ex, scoring)
        ex.statut_suggere = statut
        ex.justification_ia = just
        ex.confiance_ia = conf
        ex.preuve_ref = preuve
    return matrice
