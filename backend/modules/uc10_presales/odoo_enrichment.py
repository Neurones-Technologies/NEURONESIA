"""Étape 6 — Enrichissement Odoo du scoring (architecture v2, hybride non-figée).

Lit le miroir SQLite local (jamais Odoo en direct), en lecture seule, après le pipeline.
Produit deux blocs SANS AUCUN montant :

  ① Contexte client  — match_client(autorite_contractante)  → relation, historique, paiement
  ② Matching capacité — match_capabilities(scope AO)         → affaires similaires + gaps

Division du travail (v2) :
  - Couche A (sémantique) : ici approchée par recherche SQL sur titres + lignes de commande,
    pilotée par des ancres extraites dynamiquement (LLM). La montée en charge (embeddings
    ChromaDB indexés à la synchro) est documentée comme évolution — l'interface ne change pas.
  - Couche B (LLM)       : extraction d'ancres + classification des affaires candidates en thèmes.
  - Couche C (taxonomie) : garde-fou déterministe — exclusions, normalisation, termes critiques.

Tout échec est non-bloquant : l'enrichissement renvoie au pire des blocs vides, jamais une erreur.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import Counter
from datetime import datetime

import aiosqlite

from core.domain.offer import (
    CapabilityDeal, CapabilityMatch, ClientContext, MatchedDocument, ScoringResult,
)
from modules.uc10_presales.odoo_taxonomy import (
    find_critical_terms, is_hardware_dominated, normalize_product,
)

logger = logging.getLogger(__name__)

# Ancres de repli (si le LLM est indisponible) — volontairement courte, non exhaustive :
# la voie normale est l'extraction LLM dynamique. Ne sert que de filet de sécurité.
_SEED_ANCHORS = [
    "odoo", "erp", "fne", "syscohada", "crm", "ged", "dematerialisation",
    "developpement", "application", "workflow", "paie", "rh",
    "cisco", "fortinet", "firewall", "vmware", "wifi", "sauvegarde", "veeam",
    "microsoft 365", "sharepoint", "power bi", "sd-wan", "palo alto", "checkpoint",
]
_STOPWORDS = {"sa", "sarl", "ltd", "llc", "group", "groupe", "ci", "the", "and", "de", "du", "la", "le"}


def _strip(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c))


def _norm(text: str) -> str:
    return _strip((text or "").lower()).strip()


def _year(date_str: str | None) -> str:
    return (date_str or "")[:4]


def _is_won(stage: str | None) -> bool:
    s = _norm(stage)
    return "gagn" in s or s == "won"


def _is_lost(stage: str | None) -> bool:
    s = _norm(stage)
    return "perdu" in s or "lost" in s


def _is_cancelled(stage: str | None) -> bool:
    s = _norm(stage)
    return "annul" in s or "cancel" in s


def _status_fr(stage: str | None) -> str:
    if _is_won(stage):
        return "Gagné"
    if _is_lost(stage):
        return "Perdu"
    if _is_cancelled(stage):
        return "Annulé"
    return "En cours"


def _parse_json(raw: str):
    """Parse tolérant : retire les clôtures ```json et isole le 1er [...] ou {...}."""
    if not raw:
        return None
    txt = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"(\[.*\]|\{.*\})", txt, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


class OdooEnrichmentService:
    def __init__(self, db_path, llm=None):
        self._db_path = str(db_path)
        self._llm = llm  # LLMGateway | None — couche B (optionnelle, dégradation gracieuse)

    # ─────────────────────────────────────────────────────────────────────────
    async def enrich(self, result: ScoringResult) -> None:
        """Remplit result.client_context / capability_matches / capability_gaps et
        injecte des signaux dans strengths / points_vigilance (Niveau 2). Non-bloquant."""
        try:
            authority = (result.market_identity.autorite_contractante or "").strip()
            ctx = await self.match_client(authority)
            result.client_context = ctx

            matches, gaps = await self.match_capabilities(result)
            result.capability_matches = matches
            result.capability_gaps = gaps

            # Verser les affaires Odoo similaires dans la section « Projets similaires »
            # (taguées doc_type="odoo") — elles complètent les projets GED, souvent vides
            # sur un sujet (ex. Odoo) où nos vraies références vivent dans le CRM, pas la GED.
            self._append_odoo_projects(result)

            self._inject_signals(result)
        except Exception:  # noqa: BLE001 — jamais bloquant pour le scoring
            logger.exception("Enrichissement Odoo échoué — scoring renvoyé sans enrichissement")

    # ── ① CONTEXTE CLIENT (SQL déterministe) ─────────────────────────────────
    async def match_client(self, authority: str) -> ClientContext:
        ctx = ClientContext()
        if not authority:
            ctx.notes = "Aucun donneur d'ordre extrait de l'AO."
            return ctx

        tokens = [t for t in re.split(r"[^\w]+", _norm(authority)) if len(t) > 2 and t not in _STOPWORDS]
        if not tokens:
            ctx.notes = f"Donneur d'ordre « {authority} » non exploitable."
            return ctx

        async with aiosqlite.connect(self._db_path) as db:
            # Candidats : clients partageant au moins un token
            like_clauses = " OR ".join(["LOWER(name) LIKE ?"] * len(tokens))
            params = [f"%{t}%" for t in tokens]
            async with db.execute(
                f"SELECT client_id, name, city, country, contact_email, phone FROM clients WHERE {like_clauses}",
                params,
            ) as cur:
                candidates = await cur.fetchall()

            if not candidates:
                ctx.notes = f"« {authority} » introuvable dans Odoo — prospect / relation à créer."
                ctx.relationship_risks.append("Donneur d'ordre absent d'Odoo — aucune relation antérieure.")
                return ctx

            # Pondération par RARETÉ : un token présent dans beaucoup de clients (ex. "cote",
            # "ivoire") est peu distinctif ; "corlay" l'est beaucoup. Poids = 1/fréquence.
            weights: dict[str, float] = {}
            for t in tokens:
                async with db.execute("SELECT COUNT(*) FROM clients WHERE LOWER(name) LIKE ?", (f"%{t}%",)) as cur:
                    cnt = (await cur.fetchone())[0] or 1
                weights[t] = 1.0 / cnt

            def score(name: str) -> float:
                nn = _norm(name)
                return sum(weights[t] for t in tokens if t in nn)

            best = max(candidates, key=lambda r: score(r[1]))
            cid, name, city, country, email, phone = best
            nn = _norm(name)
            matched_toks = [t for t in tokens if t in nn]
            # Confiance fondée sur les tokens DISTINCTIFS (rares), pas les génériques
            distinctive = [t for t in matched_toks if weights[t] >= 0.05]  # token présent dans ≤20 clients
            ctx.matched = True
            ctx.odoo_client_name = (name or "").strip()
            ctx.match_confidence = (
                "EXACT" if len(matched_toks) == len(tokens) and distinctive
                else "FORTE" if distinctive
                else "FAIBLE"
            )
            ctx.city = (city or "").strip()
            ctx.country = (country or "").strip()
            ctx.known_contact = (email or phone or "").strip()

            await self._fill_history(db, cid, ctx)

        self._build_relationship_signals(ctx)
        return ctx

    async def _fill_history(self, db, cid, ctx: ClientContext) -> None:
        # Opportunités
        async with db.execute(
            "SELECT name, stage, salesperson_name, created_at FROM opportunities WHERE client_id = ?",
            (cid,),
        ) as cur:
            opps = await cur.fetchall()
        ctx.opportunities_total = len(opps)
        won = [o for o in opps if _is_won(o[1])]
        lost = [o for o in opps if _is_lost(o[1])]
        open_ops = [o for o in opps if not _is_won(o[1]) and not _is_lost(o[1]) and not _is_cancelled(o[1])]
        ctx.opportunities_won = len(won)
        ctx.opportunities_lost = len(lost)
        tranchees = len(won) + len(lost)
        ctx.win_rate_pct = round(100 * len(won) / tranchees) if tranchees else 0
        ctx.open_opportunities = [(o[0] or "").strip() for o in open_ops if o[0]][:6]
        years = [_year(o[3]) for o in opps if o[3]]
        if years:
            ctx.first_interaction = min(years)
            ctx.last_interaction = max(years)
        sp = Counter((o[2] or "").strip() for o in opps if o[2] and "test" not in _norm(o[2]))
        ctx.account_owner = sp.most_common(1)[0][0] if sp else ""
        ctx.is_existing_client = ctx.opportunities_total > 0

        # Bons de commande + technologies déployées (sans montants)
        async with db.execute(
            "SELECT date_order, order_lines FROM sale_orders WHERE client_id = ?", (cid,),
        ) as cur:
            sos = await cur.fetchall()
        ctx.orders_count = len(sos)
        if sos:
            ctx.is_existing_client = True
            oy = [_year(s[0]) for s in sos if s[0]]
            if oy:
                ctx.first_interaction = min([y for y in [ctx.first_interaction] + oy if y]) or ctx.first_interaction
                ctx.last_interaction = max([y for y in [ctx.last_interaction] + oy if y]) or ctx.last_interaction
        techs = Counter()
        for s in sos:
            try:
                for li in json.loads(s[1] or "[]"):
                    lbl = normalize_product(li.get("product") or "")
                    if lbl and len(lbl) > 2 and _norm(lbl) not in {"materiels", "services", "remise", "autres", "down payment"}:
                        techs[lbl] += 1
            except (json.JSONDecodeError, TypeError):
                continue
        ctx.deployed_technologies = [t for t, _ in techs.most_common(6)]

        # Factures — STATUT seulement, aucun montant
        async with db.execute(
            "SELECT status, due_date FROM invoices WHERE client_id = ?", (cid,),
        ) as cur:
            invs = await cur.fetchall()
        ctx.invoices_total = len(invs)
        ctx.invoices_paid = sum(1 for i in invs if i[0] == "paid")
        today = datetime.now()
        overdue = 0
        for status, due in invs:
            if status == "pending" and due:
                try:
                    if datetime.strptime(due[:10], "%Y-%m-%d") < today:
                        overdue += 1
                except ValueError:
                    pass
        ctx.invoices_overdue = overdue
        if not invs:
            ctx.payment_reliability = "INCONNUE"
        else:
            rate = ctx.invoices_paid / ctx.invoices_total
            ctx.payment_reliability = (
                "BONNE" if rate >= 0.85 and overdue <= 1
                else "MOYENNE" if rate >= 0.6
                else "À SURVEILLER"
            )

    def _build_relationship_signals(self, ctx: ClientContext) -> None:
        if ctx.is_existing_client:
            since = f" depuis {ctx.first_interaction}" if ctx.first_interaction else ""
            ctx.relationship_signals.append(f"Client existant{since} — relation établie (avantage sortant).")
        if ctx.opportunities_won >= 3:
            ctx.relationship_signals.append(
                f"{ctx.opportunities_won} affaires gagnées"
                + (f" / {ctx.opportunities_lost} perdues ({ctx.win_rate_pct}%)" if (ctx.opportunities_won + ctx.opportunities_lost) else "")
                + "."
            )
        if ctx.open_opportunities:
            ctx.relationship_signals.append(f"{len(ctx.open_opportunities)} opportunité(s) déjà en cours dans le pipeline.")
        if ctx.account_owner:
            ctx.relationship_signals.append(f"Commercial référent : {ctx.account_owner}.")
        if ctx.deployed_technologies:
            ctx.relationship_signals.append("Déjà déployé : " + ", ".join(ctx.deployed_technologies) + ".")
        if ctx.invoices_overdue >= 2:
            ctx.relationship_risks.append(
                f"{ctx.invoices_overdue} factures en retard — fiabilité de paiement à surveiller."
            )

    # ── ② MATCHING DE CAPACITÉ (ancres LLM + SQL + garde-fou + classification LLM) ─
    async def match_capabilities(self, result: ScoringResult) -> tuple[list[CapabilityMatch], list[str]]:
        scope_text = self._build_scope_text(result)
        critical = find_critical_terms(scope_text)
        anchors = await self._extract_anchors(scope_text)
        # Les termes critiques sont toujours des ancres prioritaires
        for ct in critical:
            if ct["term"] not in anchors:
                anchors.append(ct["term"])
        if not anchors:
            return [], []

        candidates = await self._search_deals(anchors)
        if not candidates:
            gaps = [f"Terme critique « {ct['term'].upper()} » exigé — aucune référence Odoo." for ct in critical]
            return [], gaps

        # Couche B : classification des candidats en thèmes (LLM, avec repli déterministe)
        groups = await self._classify_candidates(candidates, scope_text)

        crit_terms_norm = {_norm(ct["term"]) for ct in critical}
        matches: list[CapabilityMatch] = []
        matched_crit: set[str] = set()
        for theme, deals in groups.items():
            clients = sorted({d.client for d in deals if d.client})
            won = sum(1 for d in deals if d.status == "Gagné")
            theme_text = _norm(theme + " " + " ".join(d.title for d in deals))
            is_crit = any(c in theme_text for c in crit_terms_norm)
            if is_crit:
                matched_crit.update(c for c in crit_terms_norm if c in theme_text)
            from_order = any(d.source == "commande" for d in deals)
            confidence = (
                "FORTE" if (is_crit or won >= 3 or from_order)
                else "MOYENNE" if won >= 1
                else "FAIBLE"
            )
            # tri des deals : gagnés d'abord, puis récents
            deals.sort(key=lambda d: (d.status != "Gagné", -(int(d.year) if d.year.isdigit() else 0)))
            matches.append(CapabilityMatch(
                theme=theme, confidence=confidence, is_critical=is_crit,
                won_count=won, clients=clients, deals=deals[:5],
            ))
        # tri des thèmes : critiques d'abord, puis confiance, puis volume gagné
        order = {"FORTE": 0, "MOYENNE": 1, "FAIBLE": 2}
        matches.sort(key=lambda m: (not m.is_critical, order.get(m.confidence, 3), -m.won_count))

        # Gaps : termes critiques exigés mais jamais retrouvés
        gaps = [
            f"Terme critique « {ct['term'].upper()} » exigé ({ct.get('note', '')}) — aucune référence Odoo."
            for ct in critical if _norm(ct["term"]) not in matched_crit
        ]
        return matches, gaps

    def _build_scope_text(self, result: ScoringResult) -> str:
        parts = [
            result.market_identity.type_marche or "",
            (result.summary or "")[:1500],
        ]
        for p in result.profils_demandes:
            parts.append(" ".join([p.profil, p.domaine, " ".join(p.competences), " ".join(p.certifications)]))
        for e in result.key_elements:
            parts.append(str(e.value))
        parts.extend(result.besoins)
        return "\n".join(x for x in parts if x)[:6000]

    async def _extract_anchors(self, scope_text: str) -> list[str]:
        """Couche B — extraction dynamique des technologies/solutions clés (LLM), repli seed."""
        if self._llm:
            try:
                raw = await self._llm.generate(
                    system="Tu es un assistant avant-vente. Tu extrais les technologies, solutions "
                           "et modules clés d'un appel d'offres pour rechercher des projets similaires.",
                    user="Donne UNIQUEMENT un tableau JSON de 3 à 12 mots-clés courts (technologies, "
                         "solutions, modules — ex: \"Odoo\", \"FNE\", \"Cisco\", \"firewall\") à rechercher "
                         f"dans notre historique commercial.\n\nAO :\n{scope_text}\n\nJSON :",
                    max_tokens=300, temperature=0.0,
                )
                parsed = _parse_json(raw)
                if isinstance(parsed, list):
                    anchors = [_norm(str(a)) for a in parsed if str(a).strip() and len(str(a)) > 2]
                    if anchors:
                        return anchors[:12]
            except Exception:  # noqa: BLE001
                logger.warning("Extraction d'ancres LLM échouée — repli sur le seed", exc_info=True)
        # Repli déterministe
        n = _norm(scope_text)
        return [a for a in _SEED_ANCHORS if _norm(a) in n]

    async def _search_deals(self, anchors: list[str]) -> list[dict]:
        """Couche A (approchée SQL) : récupère les affaires Odoo matchant les ancres, applique
        le garde-fou matériel (couche C), dédoublonne par (client, titre)."""
        sw_anchors = {a for a in anchors if not is_hardware_dominated(a)}  # ancres logicielles
        seen: set[tuple] = set()
        out: list[dict] = []
        async with aiosqlite.connect(self._db_path) as db:
            for anchor in anchors:
                like = f"%{anchor}%"
                # Opportunités (titre)
                async with db.execute(
                    "SELECT client_name, name, stage, created_at FROM opportunities WHERE LOWER(name) LIKE ? LIMIT 60",
                    (like,),
                ) as cur:
                    for client, title, stage, created in await cur.fetchall():
                        self._add_candidate(out, seen, sw_anchors, anchor, client, title,
                                            _status_fr(stage), _year(created), "opportunité", title)
                # Bons de commande (lignes)
                async with db.execute(
                    "SELECT client_name, name, date_order, order_lines FROM sale_orders WHERE LOWER(order_lines) LIKE ? LIMIT 40",
                    (like,),
                ) as cur:
                    for client, ref, date, lines in await cur.fetchall():
                        title = self._line_title(lines, anchor) or ref
                        self._add_candidate(out, seen, sw_anchors, anchor, client, title,
                                            "Gagné", _year(date), "commande", f"{title} {lines or ''}")
        return out[:30]

    def _add_candidate(self, out, seen, sw_anchors, anchor, client, title, status, year, source, guard_text):
        title = (title or "").strip()
        client = (client or "").strip()
        if not title:
            return
        # Garde-fou couche C : ancre logicielle + affaire matérielle → on écarte (piège "module SFP")
        if anchor in sw_anchors and is_hardware_dominated(guard_text):
            return
        key = (_norm(client), _norm(title)[:40])
        if key in seen:
            return
        seen.add(key)
        out.append({"client": client, "title": title[:90], "status": status,
                    "year": year, "source": source, "anchor": anchor})

    def _line_title(self, order_lines: str | None, anchor: str) -> str:
        try:
            for li in json.loads(order_lines or "[]"):
                p = li.get("product") or ""
                if anchor in _norm(p):
                    return re.split(r"[\t#]", p, maxsplit=1)[0].strip().rstrip(":").strip()[:90]
        except (json.JSONDecodeError, TypeError):
            pass
        return ""

    async def _classify_candidates(self, candidates: list[dict], scope_text: str) -> dict[str, list[CapabilityDeal]]:
        """Couche B — range les candidats en thèmes via LLM ; repli : thème = ancre matchée."""
        def deal(c: dict) -> CapabilityDeal:
            return CapabilityDeal(client=c["client"], title=c["title"], year=c["year"],
                                  status=c["status"], source=c["source"])

        if self._llm:
            try:
                listing = "\n".join(f'{i}. {c["title"]} (client {c["client"]})' for i, c in enumerate(candidates))
                raw = await self._llm.generate(
                    system="Tu ranges des affaires commerciales passées dans des THÈMES courts et tu juges "
                           "si chacune est pertinente comme référence pour un besoin donné.",
                    user=f"Besoin (extrait de l'AO) :\n{scope_text[:1200]}\n\nAffaires :\n{listing}\n\n"
                         "Pour CHAQUE affaire, renvoie un objet "
                         "{\"i\": index, \"theme\": \"libellé court\", \"relevant\": true/false}. "
                         "Regroupe sous le même libellé exact les affaires d'un même thème. "
                         "Réponds UNIQUEMENT par un tableau JSON.",
                    max_tokens=1200, temperature=0.0,
                )
                parsed = _parse_json(raw)
                if isinstance(parsed, list):
                    groups: dict[str, list[CapabilityDeal]] = {}
                    for item in parsed:
                        try:
                            i = int(item["i"])
                        except (KeyError, ValueError, TypeError):
                            continue
                        if not item.get("relevant", True) or not (0 <= i < len(candidates)):
                            continue
                        theme = (str(item.get("theme") or "").strip() or candidates[i]["anchor"].title())[:60]
                        groups.setdefault(theme, []).append(deal(candidates[i]))
                    if groups:
                        return groups
            except Exception:  # noqa: BLE001
                logger.warning("Classification LLM échouée — repli sur le regroupement par ancre", exc_info=True)
        # Repli déterministe : un thème par ancre
        groups = {}
        for c in candidates:
            groups.setdefault(c["anchor"].title(), []).append(deal(c))
        return groups

    def _append_odoo_projects(self, result: ScoringResult, limit: int = 5) -> None:
        """Convertit les affaires Odoo (capability_matches) en projets similaires taguées
        doc_type="odoo" et les ajoute à result.similar_projects (gagnés d'abord)."""
        seen: set[tuple] = set()
        odoo_docs: list[MatchedDocument] = []
        for m in result.capability_matches:
            for d in m.deals:
                key = (_norm(d.client), _norm(d.title)[:40])
                if key in seen:
                    continue
                seen.add(key)
                score = 0.9 if d.status == "Gagné" else 0.6
                odoo_docs.append(MatchedDocument(
                    doc_id=f"odoo:{d.client}:{d.title}"[:90],
                    filename=d.title or d.client,
                    doc_type="odoo",
                    relevance_score=score,
                    excerpt=f"{d.client} — {d.year or 'n.d.'} — {d.status} · référence Odoo « {m.theme} »",
                ))
        if not odoo_docs:
            return
        odoo_docs.sort(key=lambda x: -x.relevance_score)
        result.similar_projects = list(result.similar_projects) + odoo_docs[:limit]
        logger.info("Projets similaires : +%d référence(s) Odoo ajoutée(s)", min(len(odoo_docs), limit))

    # ── Injection Niveau 2 dans le scoring ───────────────────────────────────
    def _inject_signals(self, result: ScoringResult) -> None:
        ctx = result.client_context
        for s in ctx.relationship_signals:
            result.strengths.append(f"[Odoo] {s}")
        for r in ctx.relationship_risks:
            result.points_vigilance.append(f"[Odoo] {r}")
        for m in result.capability_matches[:4]:
            tag = " (critique)" if m.is_critical else ""
            clients = ", ".join(m.clients[:3])
            result.strengths.append(
                f"[Odoo] Capacité « {m.theme} »{tag} : {m.won_count} gagnée(s) — réf. {clients}."
            )
        for g in result.capability_gaps:
            result.points_vigilance.append(f"[Odoo] {g}")
