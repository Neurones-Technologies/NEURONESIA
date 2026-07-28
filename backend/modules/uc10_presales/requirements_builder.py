"""
Consolidation ScoringResult → MatriceConformite (UC10 Pre-Sales).

C'est la GREFFE de la voie C : le pipeline de scoring existant éparpille les
exigences dans 8 champs de `ScoringResult` ; ce module les rassemble en UNE liste
d'`Exigence` typées et classées par domaine — la matrice de conformité.

GARANTIE D'EXHAUSTIVITÉ (« une exigence oubliée = offre éliminée ») : on lit
l'INTÉGRALITÉ de chaque champ (aucune troncature `[:8]` ici, contrairement aux
prompts de génération) et `expected_total` permet de vérifier qu'aucune exigence
n'a été perdue (cf. test_requirements_builder).

Champs consolidés et leur type d'exigence :
  - besoins                → BESOIN
  - criteres_selection     → CRITERE
  - prerequis              → PREREQUIS
  - ressources_demandees   → RESSOURCE   (ignoré si profils_demandes présent : doublon)
  - points_vigilance       → VIGILANCE
  - profils_demandes       → PROFIL      (effectifs/compétences détaillés, avec source)
  - seuils_eligibilite     → SEUIL       (blocking = éliminatoire)
  - appendices             → ANNEXE      (blocking = obligatoire)

NON consolidé : `criteria_breakdown` (grille de NOTATION) — c'est un artefact de
scoring, pas une exigence du CCTP, et il recoupe `criteres_selection`. L'inclure
dédoublerait la matrice.
"""

from __future__ import annotations

from core.domain.offer import (
    ScoringResult, ExtractedItem, RequiredProfile, EligibilityThreshold, Appendix,
)
from core.domain.requirements import (
    Exigence, MatriceConformite,
    TYPE_BESOIN, TYPE_CRITERE, TYPE_PREREQUIS, TYPE_RESSOURCE, TYPE_VIGILANCE,
    TYPE_PROFIL, TYPE_SEUIL, TYPE_ANNEXE,
)
from modules.uc10_presales.domain_classifier import suggested_domains


def _profil_texte(p: RequiredProfile) -> str:
    """Libellé lisible d'un profil : intitulé + qté/niveau/expérience + compétences."""
    head = p.profil
    qual = ", ".join(x for x in (
        (f"x{p.quantite}" if p.quantite else ""), p.niveau, p.experience_min,
    ) if x)
    if qual:
        head = f"{head} ({qual})"
    comps = " · ".join(list(p.competences) + list(p.certifications))
    return f"{head} — {comps}" if comps else head


def _seuil_texte(s: EligibilityThreshold) -> str:
    val = (s.valeur + (f" {s.unite}" if s.unite else "")).strip()
    return f"{s.libelle} : {val}" if val else s.libelle


def _appendix_texte(a: Appendix) -> str:
    return f"{a.code} — {a.label}" if a.code and a.code not in ("—", "") else a.label


def build_matrice(scoring: ScoringResult, *, generated_at: str = "") -> MatriceConformite:
    """Construit la matrice de conformité depuis un ScoringResult.

    `generated_at` : horodatage ISO fourni par l'appelant (pas de Date interne ici,
    pour rester pur/testable). Chaque exigence reçoit un id stable « EX-NNNN » dans
    l'ordre de consolidation, ses domaines suggérés (classifieur) et sa réf source.
    """
    # 1) Plan brut : (texte, source_ref, type, origine, blocking), texte non vide.
    #    On construit le plan AVANT de créer les Exigence pour pouvoir compter
    #    l'attendu indépendamment (garde-fou d'exhaustivité).
    plan: list[tuple[str, str, str, str, bool]] = []

    def add_items(items: list[ExtractedItem], type_: str, origine: str) -> None:
        for it in items:
            texte = (it.texte or "").strip()
            if texte:
                plan.append((texte, (it.source_section or "").strip(), type_, origine, False))

    add_items(scoring.besoins, TYPE_BESOIN, "besoins")
    add_items(scoring.criteres_selection, TYPE_CRITERE, "criteres_selection")
    add_items(scoring.prerequis, TYPE_PREREQUIS, "prerequis")

    # RESSOURCE : seulement si aucun profil structuré (sinon doublon — même logique
    # que l'affichage frontend qui masque ressources_demandees dès qu'il y a des profils).
    if scoring.profils_demandes:
        for p in scoring.profils_demandes:
            texte = _profil_texte(p).strip()
            if texte:
                plan.append((texte, (p.source_section or "").strip(), TYPE_PROFIL, "profils_demandes", False))
    else:
        add_items(scoring.ressources_demandees, TYPE_RESSOURCE, "ressources_demandees")

    add_items(scoring.points_vigilance, TYPE_VIGILANCE, "points_vigilance")

    for s in scoring.seuils_eligibilite:
        texte = _seuil_texte(s).strip()
        if texte:
            plan.append((texte, (s.source_section or "").strip(), TYPE_SEUIL, "seuils_eligibilite", bool(s.blocking)))

    for a in scoring.appendices:
        texte = _appendix_texte(a).strip()
        if texte:
            plan.append((texte, (a.source_section or "").strip(), TYPE_ANNEXE, "appendices", bool(a.obligatoire)))

    expected_total = len(plan)

    # 2) Plan → Exigences (classification par domaine sur le texte de l'exigence).
    exigences: list[Exigence] = []
    for i, (texte, source_ref, type_, origine, blocking) in enumerate(plan, start=1):
        domaines, confidence = suggested_domains(texte)
        exigences.append(Exigence(
            id=f"EX-{i:04d}",
            texte=texte,
            source_ref=source_ref,
            type=type_,
            origine=origine,
            domaines_suggeres=domaines,
            confidence=confidence,
            blocking=blocking,
        ))

    return MatriceConformite(
        ao_filename=scoring.ao_filename,
        exigences=exigences,
        generated_at=generated_at,
        expected_total=expected_total,
    )
