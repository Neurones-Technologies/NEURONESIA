import asyncio
import json
import logging
from pathlib import Path

import aiosqlite
import yaml

from config.settings import settings
from core.ports.llm_gateway import LLMGateway, OutputTruncatedError
from core.ports.document_parser import DocumentParser
from core.domain.offer import (
    ScoringResult, OfferDraft, StrategyPhase, PhaseAction, BidStrategy, Partner,
)
from core.services.rag_engine import RAGEngine
from modules.uc10_presales.scoring_pipeline import ScoringPipeline, _clean_json
from modules.uc10_presales.offer_generator import OfferGenerator
from modules.uc10_presales.odoo_enrichment import OdooEnrichmentService
from modules.uc10_presales.latency import timer, with_timeout

logger = logging.getLogger(__name__)


async def _report_progress(on_progress, step: str) -> None:
    """Appelle `on_progress(step)` s'il est fourni — no-op sinon. Petit helper partagé par
    `score_ao` et `ScoringPipeline.run` pour la remontée de progression (cf. `score_ao`)."""
    if on_progress is not None:
        await on_progress(step)


# En-deçà de ce nombre de jours avant la deadline, on bascule sur le squelette express
# (3 phases) au lieu du standard (5 phases) — forcer 5 phases serait absurde.
_EXPRESS_THRESHOLD_DAYS = 7


def _strategy_skeleton_path(express: bool) -> Path:
    name = "express" if express else "standard"
    return Path(settings.uploads_path).parent / "strategy_phases" / f"{name}.yaml"


async def _fetch_kb_team(db_path, selected_cvs: list[str]) -> dict[str, tuple[str, str]]:
    """Résout (nom_complet, titre_poste) réels depuis `kb_cv` pour les CV choisis
    (clé = `fichier_source`, alimenté par l'indexation GED). CV non encore
    résolus dans la base de connaissance : absents du dict, `offer_docx_builder`
    retombe alors sur le nom de fichier (comportement inchangé pour ceux-là)."""
    if not selected_cvs:
        return {}
    placeholders = ",".join("?" for _ in selected_cvs)
    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                f"SELECT fichier_source, nom_complet, titre_poste FROM kb_cv "
                f"WHERE fichier_source IN ({placeholders})",
                selected_cvs,
            )
            rows = await cursor.fetchall()
    except Exception:
        logger.warning("Résolution kb_cv de l'équipe échouée — repli sur le nom de fichier", exc_info=True)
        return {}
    return {fichier: (nom or "", titre or "") for fichier, nom, titre in rows if fichier}


def _days_until(date_str: str) -> int | None:
    """Nombre de jours d'ici à `date_str` (formats numériques JJ/MM/AAAA, JJ-MM-AAAA, ISO).

    Retourne None si non parsable (les mois en toutes lettres ne sont PAS gérés à dessein :
    mieux vaut retomber sur le squelette standard que déclencher l'express à tort).
    """
    import re
    from datetime import date, datetime

    if not date_str:
        return None
    s = date_str.strip()
    patterns = [
        (r"\b(\d{4})-(\d{2})-(\d{2})\b", "%Y-%m-%d", ("y", "m", "d")),
        (r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", None, ("d", "m", "y")),
    ]
    for rx, _fmt, order in patterns:
        m = re.search(rx, s)
        if not m:
            continue
        try:
            vals = dict(zip(order, (int(g) for g in m.groups())))
            target = date(vals["y"], vals["m"], vals["d"])
        except (ValueError, KeyError):
            continue
        return (target - datetime.now().date()).days
    return None


def load_strategy_skeleton(days_remaining: int | None = None) -> tuple[dict, list[StrategyPhase]]:
    """Charge le squelette de phases (standard ou express) et construit les phases vides.

    Retourne (config_brute, phases) :
    - config_brute : le YAML parsé (contient typical_actions, utilisé par le prompt LLM)
    - phases : list[StrategyPhase] sans actions (le LLM les remplira), avec start/end_day
      calculés en cumulant typical_duration_days (J1, J2-J4, ...).
    Sélection express si days_remaining < 7. Retourne ({}, []) si le YAML est illisible
    (jamais d'exception : la génération continue, le LLM produira sans squelette).
    """
    express = days_remaining is not None and days_remaining < _EXPRESS_THRESHOLD_DAYS
    path = _strategy_skeleton_path(express)
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Squelette stratégie '%s' illisible (%s) — génération sans squelette",
                       path.name, exc)
        return {}, []

    phases: list[StrategyPhase] = []
    cursor = 1
    for p in config.get("phases", []):
        if not isinstance(p, dict) or not str(p.get("id", "")).strip():
            continue
        try:
            dur = max(1, int(p.get("typical_duration_days", 1) or 1))
        except (TypeError, ValueError):
            dur = 1
        start = f"J{cursor}"
        end = start if dur == 1 else f"J{cursor + dur - 1}"
        phases.append(StrategyPhase(
            id=str(p["id"]).strip(),
            name=str(p.get("name", "") or "").strip(),
            description=" ".join(str(p.get("description", "") or "").split()),
            start_day=start,
            end_day=end,
            prerequisites=[str(x).strip() for x in (p.get("prerequisites") or []) if str(x).strip()],
            is_blocking_next=bool(p.get("is_blocking_next", False)),
        ))
        cursor += dur
    variant = config.get("variant", "express" if express else "standard")
    logger.info("Squelette stratégie '%s' chargé : %d phases (deadline_days=%s)",
                variant, len(phases), days_remaining)
    return config, phases

_STRATEGY_SYSTEM = """Tu es un directeur commercial senior chez Neurones Technologies CI, ESN ivoirienne spécialisée en intégration IT, développement logiciel, infrastructure et cybersécurité.

Tu dois produire une stratégie de réponse opérationnelle, précise et différenciante pour un appel d'offres.
Décision retenue : {decision}

━━━ RÈGLE ABSOLUE ━━━
Réponds UNIQUEMENT en JSON valide. Dans toutes les valeurs string, utilise \\n pour les sauts de ligne — PAS de vrais retours à la ligne ni de tabulations dans les valeurs JSON.

━━━ FORMAT ATTENDU ━━━
{{
  "strategy": "§1 texte.\\n\\n§2 texte.\\n\\n§3 texte.\\n\\n§4 texte.\\n\\n§5 texte.",
  "phases": [
    {{"id": "PHASE_0", "actions": [
      {{"day_label": "J1", "action": "action concrète", "responsable": "Rôle exact", "duree_estimee": "2h", "deliverable": "ce qui sort"}}
    ]}}
  ],
  "response_plan": "§1 texte.\\n\\n§2 texte.\\n\\n§3 texte.\\n\\n§4 texte."
}}

━━━ ACTEURS DE NEURONES TECHNOLOGIES CI ━━━
Utilise exclusivement ces rôles comme `responsable` :
- Directeur Commercial — pilote global, relation client, validation décisions
- Directeur Technique — architecture solution, cohérence offre technique
- Chef de Projet désigné — planning, coordination, disponibilité à valider
- Responsable RH — mobilisation profils, vérification disponibilité, CVs
- Responsable Administratif & Juridique — collecte pièces admin, caution bancaire, légalité
- Responsable Financier — BPU, chiffrage, marge, validité offre financière
- Équipe de rédaction technique — rédaction corpus offre, fiches techniques, références
- Direction Générale — validation finale, signature, engagements stratégiques

━━━ PLAN EN PHASES ━━━
- On te fournit dans le contexte un SQUELETTE DE PHASES (ids fixes, intitulés, actions types).
- Pour CHAQUE phase fournie, produis 1 à 4 actions concrètes en t'appuyant sur ses actions types.
- NE crée AUCUNE phase, NE change AUCUN id : remplis seulement le tableau `actions` de chaque id.
- Date chaque action (`day_label`) en cohérence avec start_day/end_day de la phase et la deadline réelle.
- `responsable` = un rôle EXACT de la liste ci-dessus. `deliverable` = livrable concret quand pertinent.
- PHASE_0 : mets les actions de décision/kick-off (la validation du partenaire est gérée à part, ne la duplique pas).

━━━ STRATEGY (5 paragraphes obligatoires) ━━━
§1 — Lecture stratégique de l'AO : enjeux pour le commanditaire, opportunité pour Neurones, niveau de compétition estimé, criticité du projet
§2 — Positionnement différenciant : pourquoi Neurones est bien placé, références pertinentes à valoriser, atouts sur les critères clés, expertises à mettre en avant
§3 — Axes prioritaires de l'offre : critères de sélection à surcoter, sections à soigner en priorité, angle de réponse sur les besoins identifiés
§4 — Gestion des écarts et risques : comment compenser les gaps identifiés, partenariats à mobiliser si besoin, arguments pour atténuer les faiblesses
§5 — Stratégie de prix et positionnement commercial : fourchette recommandée, arbitrages marge/compétitivité, éléments de valeur à mettre en avant pour justifier le prix

━━━ RESPONSE_PLAN (4 paragraphes obligatoires) ━━━
§1 — Organisation de l'équipe de réponse : qui fait quoi, point de coordination, cadence des revues internes
§2 — Documents et informations à rassembler en priorité : liste précise des pièces admin (RCCM, DGI, CNPS, bilans N-1/N-2/N-3, statuts, pouvoirs de signature), preuves de références (attestations, PV de recette), CVs à actualiser
§3 — Points de vérification critiques avant dépôt : conformité administrative, cohérence technique/financière, respect du plan de présentation exigé, vérification des délais de validité des documents
§4 — Facteurs de succès et pièges à éviter : erreurs fréquentes sur ce type d'AO, points sur lesquels les dossiers sont souvent rejetés, éléments différenciants à ne pas oublier"""


# ── Prompts SCINDÉS pour génération PARALLÈLE (3 appels Sonnet concurrents au lieu d'un
#    bloc unique de 8000 tokens ~220s → wall-clock divisé par ~3). Chaque appel produit moins
#    de tokens et tourne en //. strategy/plan = texte brut ; phases = JSON. ──────────────────
_STRATEGY_TEXT_SYSTEM = """Tu es un directeur commercial senior chez Neurones Technologies CI (ESN ivoirienne : intégration IT, dev logiciel, infrastructure, cybersécurité).
Décision retenue : {decision}

Produis UNIQUEMENT la STRATÉGIE de réponse, en 5 paragraphes, en TEXTE BRUT (pas de markdown, pas de JSON, pas de titres), séparés par une ligne vide :
§1 — Lecture stratégique de l'AO : enjeux pour le commanditaire, opportunité pour Neurones, niveau de compétition estimé, criticité du projet
§2 — Positionnement différenciant : pourquoi Neurones est bien placé, références pertinentes à valoriser, atouts sur les critères clés
§3 — Axes prioritaires de l'offre : critères de sélection à surcoter, sections à soigner, angle de réponse sur les besoins
§4 — Gestion des écarts et risques : comment compenser les gaps, partenariats à mobiliser, arguments pour atténuer les faiblesses
§5 — Stratégie de prix et positionnement commercial : fourchette recommandée, arbitrages marge/compétitivité, valeur à mettre en avant
Ne cite que ce qui est dans le contexte fourni. Réponds uniquement avec les 5 paragraphes."""

_RESPONSE_PLAN_SYSTEM = """Tu es un directeur commercial senior chez Neurones Technologies CI.

Produis UNIQUEMENT le PLAN DE RÉPONSE opérationnel, en 4 paragraphes, en TEXTE BRUT (pas de markdown, pas de JSON, pas de titres), séparés par une ligne vide :
§1 — Organisation de l'équipe de réponse : qui fait quoi, coordination, cadence des revues
§2 — Documents à rassembler en priorité : pièces admin (RCCM, DGI, CNPS, bilans N-1/N-2/N-3, statuts, pouvoirs de signature), preuves de références (attestations, PV de recette), CVs à actualiser
§3 — Points de vérification critiques avant dépôt : conformité administrative, cohérence technique/financière, respect du plan exigé, délais de validité des documents
§4 — Facteurs de succès et pièges à éviter : erreurs fréquentes, motifs de rejet, éléments différenciants
Réponds uniquement avec les 4 paragraphes."""

_PHASES_SYSTEM = """Tu es un directeur commercial senior chez Neurones Technologies CI.
Décision retenue : {decision}

On te fournit un SQUELETTE DE PHASES (ids fixes, intitulés, actions types). Pour CHAQUE phase, produis 1 à 4 actions concrètes. NE crée AUCUNE phase, NE change AUCUN id.

`responsable` = un rôle EXACT parmi : Directeur Commercial, Directeur Technique, Chef de Projet désigné, Responsable RH, Responsable Administratif & Juridique, Responsable Financier, Équipe de rédaction technique, Direction Générale.
Date chaque action (`day_label`) en cohérence avec start_day/end_day de la phase et la deadline. `deliverable` = livrable concret. PHASE_0 = actions de décision/kick-off (la validation partenaire est gérée à part, ne pas dupliquer).

Réponds UNIQUEMENT en JSON valide, \\n pour les sauts de ligne dans les valeurs :
{
  "phases": [
    {"id": "PHASE_0", "actions": [
      {"day_label": "J1", "action": "action concrète", "responsable": "Rôle exact", "duree_estimee": "2h", "deliverable": "ce qui sort"}
    ]}
  ]
}"""


class PresalesUseCase:
    """
    UC10 — Avant-vente : scoring AO + génération d'offre technique.
    Logique métier pure — utilise uniquement les ports (interfaces).
    """

    def __init__(
        self,
        llm_haiku: LLMGateway,
        llm_sonnet: LLMGateway,
        rag_engine: RAGEngine,
        pdf_parser: DocumentParser,
        docx_parser: DocumentParser,
        vision_ocr=None,
    ):
        # Étape 4 (analyse/notation/reco = décision) sur Sonnet ; extraction sur Haiku.
        # Bascule via settings.presales_analysis_model sans toucher au code.
        analysis_llm = llm_sonnet if settings.presales_analysis_model == "sonnet" else llm_haiku
        self._pipeline = ScoringPipeline(llm=llm_haiku, rag_engine=rag_engine, llm_analysis=analysis_llm)
        # llm_premium=Sonnet → offre + qualitative si settings.offer_sections_model == "sonnet".
        self._generator = OfferGenerator(llm=llm_haiku, llm_premium=llm_sonnet)
        self._llm_sonnet = llm_sonnet
        self._pdf_parser = pdf_parser
        self._docx_parser = docx_parser
        # Repli vision (transcription Claude) pour les AO scannés : DocumentVisionExtractor
        # exposant transcribe_pdf_bytes, ou None si la vision est désactivée. Voir _vision_ocr.
        self._vision_ocr = vision_ocr
        self._odoo_enrichment = OdooEnrichmentService(db_path=settings.local_db_path, llm=llm_haiku)

    async def score_ao(
        self, filename: str, file_bytes: bytes, on_progress=None,
    ) -> ScoringResult:
        """`on_progress` (optionnel) : callback async `async def(step: str) -> None`,
        appelé à chaque grande étape — permet au caller (ex. `_run_analysis_task` en mode
        202+polling) de remonter une progression lisible plutôt qu'un statut figé "scoring"."""
        await _report_progress(on_progress, "Extraction du texte du document")
        with timer("score_ao.extract_text"):
            text = await self._extract_text(filename, file_bytes)
        # AO scanné (aucune couche texte extraite) → repli sur la transcription vision Claude
        # avant d'abandonner. Ne se déclenche que si l'extraction texte/OCR n'a rien donné.
        if not text.strip():
            text = await self._vision_ocr_fallback(filename, file_bytes)
        if not text.strip():
            raise ValueError(
                f"Impossible d'extraire le texte de « {filename} ». "
                "Ce PDF semble être entièrement scanné (images sans couche texte) et la "
                "transcription automatique n'a rien pu lire. Vérifiez que le document est "
                "lisible, ou installez Tesseract OCR avec le pack français (fra) "
                "(https://github.com/UB-Mannheim/tesseract/wiki), puis relancez."
            )
        with timer("score_ao.pipeline"):
            result = await with_timeout(
                self._pipeline.run(ao_filename=filename, ao_text=text, on_progress=on_progress),
                "pipeline.run",
            )
        # Étape 6 — enrichissement Odoo (non-bloquant : ne casse jamais le scoring)
        with timer("score_ao.odoo_enrich"):
            await self._odoo_enrichment.enrich(result)
        return result

    async def generate_offer(
        self,
        scoring: ScoringResult,
        client_name: str = "",
        selected_cvs: list[str] | None = None,
        selected_abes: list[str] | None = None,
    ) -> OfferDraft:
        return await self._generator.generate(
            scoring=scoring,
            client_name=client_name,
            selected_cvs=selected_cvs,
            selected_abes=selected_abes,
        )

    async def build_offer_sections(
        self,
        scoring: ScoringResult,
        client_name: str = "",
    ) -> tuple[dict, str, str]:
        """Étape 1 : sections éditables (LLM), sans .docx."""
        with timer("offer.build_sections"):
            return await with_timeout(
                self._generator.build_sections(scoring=scoring, client_name=client_name),
                "offer.build_sections")

    async def render_offer(
        self,
        scoring: ScoringResult,
        sections: dict,
        client_name: str = "",
        selected_cvs: list[str] | None = None,
        selected_abes: list[str] | None = None,
    ) -> OfferDraft:
        """Étape 2 : .docx à partir des sections (éventuellement éditées).

        Le tableau « Équipe projet » est alimenté par les vraies données
        `kb_cv` (nom complet, titre de poste) quand elles sont disponibles,
        plutôt que devinées depuis le nom de fichier du CV."""
        kb_team = await _fetch_kb_team(settings.local_db_path, selected_cvs or [])
        return self._generator.render(
            scoring, sections, client_name, selected_cvs, selected_abes, kb_team=kb_team
        )

    async def generate_bid_strategy(
        self,
        scoring: ScoringResult,
        client_name: str = "",
        decision: str = "GO",
        decision_reason: str = "",
        partner: Partner | None = None,
    ) -> BidStrategy:
        decision_label = {"GO": "GO — Répondre", "CONDITIONAL": "CONDITIONNEL — Sous conditions", "NO_BID": "NO-BID — Ne pas répondre"}.get(decision, decision)

        # Extraire les éléments clés du scoring
        key_map: dict[str, str] = {e.category.lower(): e.value for e in scoring.key_elements}
        date_remise = scoring.date_remise or key_map.get("date de remise", key_map.get("délai", "non précisé"))
        budget = key_map.get("budget", key_map.get("montant", "non précisé"))
        type_marche = key_map.get("type de marché", key_map.get("type marché", "non précisé"))
        secteur = key_map.get("secteur", "non précisé")
        livrables = key_map.get("livrables", "non précisé")

        # Sélection du squelette (standard 5 phases / express 3 phases) sur les jours restants
        deadline_src = scoring.market_identity.deadline_soumission or date_remise
        days_remaining = _days_until(deadline_src)
        config, skeleton = load_strategy_skeleton(days_remaining)

        lines = [
            "═══ CONTEXTE AO ═══",
            f"Intitulé AO : {scoring.ao_filename}",
            f"Client / Commanditaire : {client_name or 'Non précisé'}",
            f"Secteur : {secteur}",
            f"Type de marché : {type_marche}",
            f"Budget estimé : {budget}",
            f"DATE DE REMISE : {date_remise}"
            + (f"  (≈ {days_remaining} jours restants)" if days_remaining is not None else "")
            + "  ← date les actions par rapport à cette échéance",
            f"Score GED Neurones : {scoring.score}/100",
            f"Décision retenue : {decision_label}",
        ]
        if partner is not None:
            lines.append(f"PARTENAIRE DE GROUPEMENT : {partner.name} ({partner.role}, {partner.type})")
        lines += ["", "═══ RÉSUMÉ AO ═══", scoring.summary[:800], ""]

        # Squelette de phases à remplir (ids fixes, intitulés, actions types)
        if skeleton:
            phase_lines = ["═══ SQUELETTE DE PHASES À REMPLIR (ne pas changer les ids) ═══"]
            raw_by_id = {str(p.get("id")): p for p in config.get("phases", [])}
            for ph in skeleton:
                typ = raw_by_id.get(ph.id, {}).get("typical_actions", []) or []
                phase_lines.append(f"  {ph.id} — {ph.name} ({ph.start_day}→{ph.end_day})")
                for ta in typ:
                    phase_lines.append(f"      · {ta}")
            lines += phase_lines + [""]

        if scoring.criteres_selection:
            lines += ["═══ CRITÈRES DE SÉLECTION (à surcoter) ═══"] + [f"  • {c.texte}" for c in scoring.criteres_selection[:8]] + [""]

        if scoring.besoins:
            lines += ["═══ BESOINS IDENTIFIÉS ═══"] + [f"  • {b.texte}" for b in scoring.besoins[:8]] + [""]

        if scoring.ressources_demandees:
            lines += ["═══ PROFILS & RESSOURCES DEMANDÉS ═══"] + [f"  • {r.texte}" for r in scoring.ressources_demandees[:8]] + [""]

        if scoring.prerequis:
            lines += ["═══ PRÉREQUIS (administratifs, techniques, certifications) ═══"] + [f"  • {p.texte}" for p in scoring.prerequis[:8]] + [""]

        if scoring.points_vigilance:
            lines += ["═══ POINTS DE VIGILANCE ═══"] + [f"  • {v.texte}" for v in scoring.points_vigilance[:6]] + [""]

        if livrables and livrables != "non précisé":
            lines += ["═══ LIVRABLES ATTENDUS ═══", livrables, ""]

        if scoring.strengths:
            lines += ["═══ FORCES DE NEURONES SUR CET AO ═══"] + [f"  + {s}" for s in scoring.strengths[:6]] + [""]

        if scoring.risks:
            risk_lines = [
                f"  - [{r.criticite}] {r.label}" + (f" → Mitigation : {r.mitigation}" if r.mitigation else "")
                for r in scoring.risks[:6]
            ]
            lines += ["═══ RISQUES & FAIBLESSES ═══"] + risk_lines + [""]

        if scoring.gaps_analysis:
            lines += ["═══ ANALYSE DES ÉCARTS (ce qui manque / ce qu'il faut compenser) ═══", scoring.gaps_analysis[:500], ""]

        if decision_reason:
            lines += ["═══ JUSTIFICATION DE LA DÉCISION ═══", decision_reason, ""]

        user = "\n".join(lines)

        # 3 appels Sonnet EN PARALLÈLE (au lieu d'un bloc unique de 8000 tokens ≈ 220s) :
        # stratégie (texte) ∥ plan de réponse (texte) ∥ phases (JSON). Chacun produit moins de
        # tokens et tourne en concurrence → wall-clock ≈ le plus lent des 3 (~70-90s) au lieu de la somme.
        with timer("bid_strategy.generate"):
            strategy_text, response_plan, phases_raw = await with_timeout(
                asyncio.gather(
                    self._gen_strategy_block(_STRATEGY_TEXT_SYSTEM.replace("{decision}", decision_label), user, 2500, "stratégie"),
                    self._gen_strategy_block(_RESPONSE_PLAN_SYSTEM, user, 2000, "plan de réponse"),
                    self._gen_phases_block(_PHASES_SYSTEM.replace("{decision}", decision_label), user),
                ),
                "bid_strategy.gather",
            )
        strategy_text = strategy_text or "Génération indisponible — veuillez réessayer."
        phases = self._merge_phase_actions(skeleton, phases_raw)

        # PHASE_0 (validation) = préalables du scoring, réutilisés tels quels (pas de duplication)
        partner_validation = list(scoring.preconditions)

        from datetime import datetime
        logger.info(
            "Bid strategy générée : variant=%s, %d phases, %d actions, %d préalables",
            config.get("variant", "?"), len(phases),
            sum(len(p.actions) for p in phases), len(partner_validation),
        )
        return BidStrategy(
            phases=phases,
            strategy_text=strategy_text,
            response_plan=response_plan,
            appendices=list(scoring.appendices),
            partner=partner,
            partner_validation=partner_validation,
            generated_at=datetime.now().isoformat(timespec="seconds"),
        )

    async def _gen_strategy_block(self, system: str, user: str, max_tokens: int, label: str) -> str:
        """Un bloc TEXTE de la stratégie (stratégie ou plan de réponse). Dégradation gracieuse."""
        try:
            txt = await self._llm_sonnet.generate(
                system=system, user=user, max_tokens=max_tokens,
                raise_on_truncation=True, temperature=0.7,
            )
            return txt.strip()
        except OutputTruncatedError as exc:
            logger.warning("Bloc '%s' tronqué (%d tok) — texte partiel conservé.", label, exc.max_tokens)
            return (exc.partial_text or "").strip()
        except Exception as exc:
            logger.warning("Bloc '%s' échoué (%s) — vide.", label, exc)
            return ""

    async def _gen_phases_block(self, system: str, user: str) -> object:
        """Le bloc PHASES (JSON) de la stratégie. Retourne la liste `phases` ou None (squelette vide)."""
        try:
            # 5000 : sur un AO riche, 5 phases × jusqu'à 4 actions détaillées dépassent 3000 tok
            # → JSON coupé → 0 action. 5000 laisse de la marge tout en restant le bloc le plus lent
            # des 3 appels // (donc il fixe le wall-clock de la phase B, ~60-80s).
            raw = await self._llm_sonnet.generate(
                system=system, user=user, max_tokens=5000,
                raise_on_truncation=True, temperature=0.7,
            )
        except OutputTruncatedError as exc:
            logger.warning("Phases stratégie tronquées (%d tok) — parse de récupération.", exc.max_tokens)
            raw = exc.partial_text
        except Exception as exc:
            logger.warning("Phases stratégie échouées (%s) — squelette sans actions.", exc)
            return None
        try:
            return json.loads(_clean_json(raw)).get("phases")
        except Exception as exc:
            logger.warning("Phases JSON parse failed (%s) — squelette sans actions.", exc)
            return None

    # Rôles autorisés (whitelist du prompt) — sert à normaliser le responsable retourné
    _STRATEGY_ROLES = {
        "directeur commercial", "directeur technique", "chef de projet désigné",
        "responsable rh", "responsable administratif & juridique", "responsable financier",
        "équipe de rédaction technique", "direction générale",
    }

    def _merge_phase_actions(
        self, skeleton: list[StrategyPhase], raw_phases: object
    ) -> list[StrategyPhase]:
        """Fusionne les actions produites par le LLM (par id de phase) dans le squelette.

        Le squelette (ids, intitulés, dépendances) fait foi ; le LLM ne fournit que les actions.
        Une phase sans actions LLM reste dans le plan (vide) — dégradation gracieuse.
        """
        actions_by_id: dict[str, list] = {}
        if isinstance(raw_phases, list):
            for item in raw_phases:
                if isinstance(item, dict) and str(item.get("id", "")).strip():
                    acts = item.get("actions", [])
                    actions_by_id[str(item["id"]).strip()] = acts if isinstance(acts, list) else []
        for phase in skeleton:
            phase.actions = []
            for a in actions_by_id.get(phase.id, []):
                if not isinstance(a, dict):
                    continue
                action_txt = str(a.get("action", "") or "").strip()
                if not action_txt:
                    continue
                phase.actions.append(PhaseAction(
                    day_label=str(a.get("day_label", "") or "").strip() or phase.start_day,
                    action=action_txt,
                    responsable=str(a.get("responsable", "") or "").strip(),
                    duree_estimee=str(a.get("duree_estimee", "") or "").strip(),
                    deliverable=str(a.get("deliverable", "") or "").strip(),
                ))
        return skeleton

    async def match_team(self, req) -> dict:
        """Cherche dans la GED les CVs correspondant aux profils demandés par l'AO."""
        from modules.uc10_presales.schemas import TeamMatchResponse, TeamMatchProfile

        query_parts = [p for p in req.requirements[:6] if p.strip()]
        if req.ao_context:
            query_parts = [req.ao_context[:300]] + query_parts
        query = " ".join(query_parts) if query_parts else "ingénieur développeur"

        try:
            sources = await self._pipeline._rag_engine.search(
                query=query,
                filter_metadata={"doc_type": "cv"},
                top_k=req.top_k,
            )
        except Exception:
            sources = []

        profiles = []
        for src in sources:
            name = src.filename.replace(".docx", "").replace(".pdf", "").replace("-", " ").replace("_", " ")
            if name.lower().startswith("cv "):
                name = name[3:]
            profiles.append(TeamMatchProfile(
                filename=src.filename,
                name=name.strip().title(),
                excerpt=src.excerpt[:400],
                relevance_score=round(src.relevance_score, 2),
            ))

        return TeamMatchResponse(profiles=profiles, query_used=query[:200])

    async def _vision_ocr_fallback(self, filename: str, file_bytes: bytes) -> str:
        """Transcrit un AO PDF scanné via la vision Claude quand l'extraction texte/OCR
        n'a rien donné. Best-effort : renvoie '' (jamais d'exception) si la vision est
        indisponible, si le fichier n'est pas un PDF, ou si la transcription échoue —
        `score_ao` lèvera alors le ValueError explicite."""
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext != "pdf" or self._vision_ocr is None or not getattr(self._vision_ocr, "available", False):
            return ""
        try:
            with timer("score_ao.vision_ocr"):
                text = await self._vision_ocr.transcribe_pdf_bytes(
                    file_bytes, max_pages=settings.ocr_max_pages)
        except Exception:
            logger.warning("Transcription vision de l'AO « %s » échouée", filename, exc_info=True)
            return ""
        if text.strip():
            logger.info(
                "AO scanné « %s » transcrit par vision Claude (%d caractères) — "
                "repli après extraction texte/OCR vide.", filename, len(text),
            )
        return text

    async def _extract_text(self, filename: str, file_bytes: bytes) -> str:
        import tempfile
        import os
        ext = filename.lower().rsplit(".", 1)[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            if ext == "pdf":
                return await self._pdf_parser.parse(tmp_path)
            elif ext in ("docx", "doc"):
                return await self._docx_parser.parse(tmp_path)
            else:
                return file_bytes.decode("utf-8", errors="ignore")
        finally:
            os.unlink(tmp_path)
