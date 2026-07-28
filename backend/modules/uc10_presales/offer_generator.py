"""
OfferGenerator — génération d'offre technique **sans template**.

Principe : l'IA ne remplit plus un gabarit .docx. Elle produit un PLAN DE DOCUMENT
(une couverture + une liste de blocs typés), et `offer_docx_builder` met ce plan en
forme dans un Word à la charte Neurones, entièrement construit par le code.

Flux en 2 temps (endpoints /offer/sections puis /offer/render), plus /generate (1 passe) :
  1. `build_sections` → appel LLM → plan de document éditable {cover, blocks} + domaine + client
  2. `render`         → `offer_docx_builder.build_offer_docx` → bytes .docx

Robustesse : parse tolérant du JSON (récupération partielle si tronqué) et repli
déterministe (`_fallback_document`) construit à partir du scoring — on ne produit
jamais un document vide, même si le LLM échoue totalement.
"""

import json
import logging
import re

from core.ports.llm_gateway import LLMGateway, OutputTruncatedError
from core.domain.offer import ScoringResult, OfferDraft
from config.settings import settings
from modules.uc10_presales.scoring_pipeline import _clean_json
from modules.uc10_presales.domain_classifier import primary_domain
from modules.uc10_presales.offer_docx_builder import build_offer_docx, _cover_date_parts

logger = logging.getLogger(__name__)


# ── Contexte utilisateur (matière de l'offre) ─────────────────────────────────

def _offer_user_context(scoring: ScoringResult, client_name: str, domain: str,
                        delai: str, budget: str) -> str:
    """Contexte ENRICHI fourni au LLM pour rédiger une offre DIFFÉRENCIANTE : résumé,
    besoins, critères à surcoter, atouts, risques+mitigations, écarts, profils, signaux
    client (Odoo) et références. Tout provient du ScoringResult — aucun appel LLM ici."""
    lines = [
        f"AO : {scoring.ao_filename}",
        f"Client : {client_name or 'Non précisé'}",
        f"Domaine : {domain}",
        f"Délai de livraison : {delai}",
        f"Budget estimé : {budget}",
        "",
        "RÉSUMÉ DE L'AO :",
        scoring.summary[:900] if scoring.summary else "(non disponible)",
    ]
    if scoring.besoins:
        lines += ["", "BESOINS IDENTIFIÉS :"] + [f"- {b.texte}" for b in scoring.besoins[:12]]
    if scoring.criteres_selection:
        lines += ["", "CRITÈRES DE SÉLECTION À SURCOTER (soigner ces angles) :"] + \
                 [f"- {c.texte}" for c in scoring.criteres_selection[:8]]
    if scoring.strengths:
        lines += ["", "ATOUTS DE NEURONES À VALORISER (différenciateurs) :"] + \
                 [f"+ {s}" for s in scoring.strengths[:6]]
    if scoring.risks:
        lines += ["", "RISQUES À ADRESSER DANS L'OFFRE (montrer la maîtrise) :"] + \
                 [f"- [{r.criticite}] {r.label}" + (f" → {r.mitigation}" if r.mitigation else "")
                  for r in scoring.risks[:6]]
    if scoring.gaps_analysis:
        lines += ["", "ÉCARTS À COMPENSER :", scoring.gaps_analysis[:400]]
    if scoring.profils_demandes:
        lines += ["", "PROFILS ATTENDUS :"] + \
                 [f"- {p.profil}" + (f" ({p.domaine})" if p.domaine else "")
                  for p in scoring.profils_demandes[:8]]
    cc = getattr(scoring, "client_context", None)
    if cc is not None and getattr(cc, "matched", False):
        sig: list[str] = []
        if cc.is_existing_client:
            sig.append("client existant de Neurones")
        if cc.deployed_technologies:
            sig.append("technologies déjà déployées chez lui : " + ", ".join(cc.deployed_technologies[:6]))
        sig += list(cc.relationship_signals[:3])
        if sig:
            lines += ["", "CONTEXTE CLIENT (historique Odoo, à exploiter avec tact) :"] + \
                     [f"· {s}" for s in sig]
    refs = [d.filename for d in (scoring.similar_projects or [])][:5]
    if refs:
        lines += ["", "RÉFÉRENCES MOBILISABLES (projets similaires en GED) :"] + [f"· {r}" for r in refs]
    return "\n".join(lines)


# ── Prompt système : plan de document ─────────────────────────────────────────

_DOCUMENT_SYSTEM = """\
Tu es expert en rédaction d'offres techniques IT pour Neurones Technologies CI.
À partir du scoring d'un appel d'offres, tu CONÇOIS toi-même la structure d'une offre
technique et tu la renvoies en JSON strict, comme un PLAN DE DOCUMENT : une couverture
et une liste de blocs. Tu choisis librement les sections, leur ordre et leur profondeur,
pour qu'elles collent à CET appel d'offres précis.

Réponds UNIQUEMENT par un objet JSON de cette forme :

{
  "cover": {
    "titre": "Titre de l'offre (6-12 mots, commence par un verbe d'action : Développement / Mise en place / Conception / Déploiement)",
    "sous_titre": "Offre technique",
    "accroche": "Une phrase d'accroche qui résume la valeur de la réponse (facultatif)"
  },
  "blocks": [
    {"type": "heading", "level": 1, "text": "Titre de section principale"},
    {"type": "paragraph", "text": "Un paragraphe de texte."},
    {"type": "heading", "level": 2, "text": "Sous-section"},
    {"type": "bullets", "items": ["point 1", "point 2"]},
    {"type": "numbered", "items": ["étape 1", "étape 2"]},
    {"type": "table", "titre": "Titre du tableau", "headers": ["Colonne A", "Colonne B"], "rows": [["a1", "b1"], ["a2", "b2"]]},
    {"type": "page_break"}
  ]
}

Types de blocs AUTORISÉS (aucun autre) : heading (level 1, 2 ou 3), paragraph, bullets,
numbered, table, page_break.

Contenu ATTENDU dans "blocks" (organise-le en sections avec des heading de niveau 1) :
- Compréhension du besoin et du contexte du client (cite son secteur, ses enjeux, son nom réel).
- Objectifs de la réponse et livrables attendus.
- Approche et architecture technique proposées (cite les VRAIES technologies adaptées).
- Description détaillée de la solution : modules / fonctionnalités (heading 2 + paragraphes).
- Stack technique : un bloc "table" (colonnes Composant | Version/Précision).
- Répartition des fonctionnalités par couche technique : un bloc "table" (Fonctionnalité | Composant).
- Planning prévisionnel en jours-homme : un bloc "table" (Phase | Activité | J/H), avec une ligne TOTAL.
- Valeur ajoutée et différenciateurs de Neurones pour cet AO.

N'INCLUS PAS ces éléments (ils sont ajoutés automatiquement, ne les répète pas) :
- présentation générale de la société Neurones Technologies ;
- méthodologie / gestion de projet générique ;
- tableau nominatif de l'équipe projet ;
- certifications / engagements qualité génériques ;
- page de garde (elle est produite à partir de "cover").

Règles de rédaction :
- Rédige en français, dans un style professionnel d'offre commerciale.
- Sois SPÉCIFIQUE à cet AO et à ce client : bannis tout texte générique passe-partout.
- Valorise les atouts fournis, montre la maîtrise des risques, soigne les critères à surcoter.
- Dans les strings JSON, utilise \\n pour un retour à la ligne — JAMAIS de vrai retour à la ligne.
- Renvoie du JSON valide et RIEN d'autre (pas de texte avant/après, pas de balises Markdown).
"""


def _build_document_system() -> str:
    return _DOCUMENT_SYSTEM


# ── Parse tolérant du plan de document ────────────────────────────────────────

_ALLOWED_BLOCK_TYPES = {"heading", "paragraph", "bullets", "numbered", "table", "page_break"}


def _sanitize_block(raw: object) -> dict | None:
    """Valide/normalise un bloc issu du LLM. Retourne None si inexploitable."""
    if not isinstance(raw, dict):
        return None
    btype = str(raw.get("type", "")).strip().lower()
    if btype not in _ALLOWED_BLOCK_TYPES:
        return None
    if btype == "heading":
        text = str(raw.get("text", "") or "").strip()
        if not text:
            return None
        try:
            level = min(max(int(raw.get("level", 1)), 1), 3)
        except (TypeError, ValueError):
            level = 1
        return {"type": "heading", "level": level, "text": text}
    if btype == "paragraph":
        text = str(raw.get("text", "") or "").strip()
        return {"type": "paragraph", "text": text} if text else None
    if btype in ("bullets", "numbered"):
        items = [str(i).strip() for i in (raw.get("items") or []) if str(i).strip()]
        return {"type": btype, "items": items} if items else None
    if btype == "table":
        headers = [str(h).strip() for h in (raw.get("headers") or [])]
        rows = [[str(c).strip() for c in r] for r in (raw.get("rows") or []) if isinstance(r, list)]
        if not headers and not rows:
            return None
        return {"type": "table", "titre": str(raw.get("titre", "") or "").strip(),
                "headers": headers, "rows": rows}
    if btype == "page_break":
        return {"type": "page_break"}
    return None


def _salvage_blocks(text: str) -> list[dict]:
    """Récupère des blocs exploitables d'un JSON tronqué : parse chaque objet {...}
    de premier niveau du tableau "blocks" indépendamment (best effort)."""
    m = re.search(r'"blocks"\s*:\s*\[', text)
    if not m:
        return []
    out: list[dict] = []
    depth, start = 0, None
    for j in range(m.end(), len(text)):
        ch = text[j]
        if ch == "{":
            if depth == 0:
                start = j
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    block = _sanitize_block(json.loads(text[start:j + 1]))
                    if block:
                        out.append(block)
                except Exception:
                    pass
                start = None
        elif ch == "]" and depth == 0:
            break
    return out


def _parse_document(raw: str) -> dict:
    """Plan de document {cover, blocks} depuis la sortie LLM, avec récupération partielle.

    - JSON complet valide → normalisé.
    - JSON cassé/tronqué → on sauve la couverture (regex) et les blocs récupérables.
    Retourne {} si rien n'est exploitable (le repli déterministe prend alors le relais)."""
    cleaned = _clean_json(raw or "")
    cover: dict = {}
    blocks: list[dict] = []
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            c = obj.get("cover")
            if isinstance(c, dict):
                cover = {k: str(c.get(k, "") or "").strip() for k in ("titre", "sous_titre", "accroche")}
            blocks = [b for b in (_sanitize_block(x) for x in (obj.get("blocks") or [])) if b]
            return {"cover": cover, "blocks": blocks}
    except Exception:
        pass
    # Récupération best effort
    for key in ("titre", "sous_titre", "accroche"):
        mm = re.search(r'"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned)
        if mm:
            cover[key] = mm.group(1).replace('\\"', '"').replace('\\n', '\n').strip()
    blocks = _salvage_blocks(cleaned)
    if not cover and not blocks:
        return {}
    return {"cover": cover, "blocks": blocks}


# ── Repli déterministe (jamais de document vide) ──────────────────────────────

def _fallback_document(scoring: ScoringResult, client_name: str) -> dict:
    """Plan de document minimal construit à partir du scoring, si le LLM échoue.
    Offre correcte quoique générique — meilleure qu'une erreur ou un fichier vide."""
    client = client_name or "le client"
    ao_short = scoring.ao_filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
    besoins = [b.texte for b in scoring.besoins][:8]
    blocks: list[dict] = [
        {"type": "heading", "level": 1, "text": "Compréhension du besoin"},
        {"type": "paragraph", "text":
            f"Dans le cadre de « {ao_short} », {client} sollicite Neurones Technologies pour "
            "la réalisation d'un projet informatique. " +
            (scoring.summary[:600] if scoring.summary else "")},
    ]
    if besoins:
        blocks += [
            {"type": "heading", "level": 2, "text": "Besoins identifiés"},
            {"type": "bullets", "items": besoins},
        ]
    blocks += [
        {"type": "heading", "level": 1, "text": "Notre réponse"},
        {"type": "paragraph", "text":
            "Neurones Technologies propose une solution performante, sécurisée et évolutive, "
            "parfaitement adaptée aux besoins exprimés, livrée dans les délais et le budget convenus."},
    ]
    if scoring.strengths:
        blocks += [
            {"type": "heading", "level": 1, "text": "Valeur ajoutée"},
            {"type": "bullets", "items": list(scoring.strengths[:6])},
        ]
    return {
        "cover": {"titre": f"Développement d'une solution — {ao_short}",
                  "sous_titre": "Offre technique", "accroche": ""},
        "blocks": blocks,
    }


# ── Helpers scoring ───────────────────────────────────────────────────────────

def _detect_domain(scoring: ScoringResult) -> str:
    """Domaine principal de l'AO (sert d'indice de contexte au prompt)."""
    text = scoring.summary + " " + " ".join(e.value for e in scoring.key_elements)
    return primary_domain(text)


def _extract_client_from_scoring(scoring: ScoringResult) -> str:
    """Tente d'extraire le nom du client depuis les key_elements."""
    for e in scoring.key_elements:
        if any(k in e.category.lower() for k in ("client", "commanditaire", "maître", "donneur")):
            v = e.value.strip()
            if v and v.lower() not in ("non précisé", "inconnu", ""):
                return v
    return ""


# ── Classe principale ─────────────────────────────────────────────────────────

class OfferGenerator:

    def __init__(self, llm: LLMGateway, llm_premium: LLMGateway | None = None):
        self._llm = llm
        # Modèle « premium » optionnel (Sonnet) pour une offre + qualitative ; activé via
        # settings.offer_sections_model == "sonnet". None → toujours Haiku.
        self._llm_premium = llm_premium

    @staticmethod
    def build_filename(scoring: ScoringResult, client_name: str = "") -> str:
        """Nom du fichier généré : « Offre_Technique_<client>__<Mois>_<Année>.docx »."""
        raw = client_name.strip() if client_name and client_name.strip() else "Client"
        safe_client = re.sub(r"\s+", "_", raw)
        safe_client = re.sub(r'[\\/:*?"<>|]', "-", safe_client)
        mois, annee = _cover_date_parts()
        return f"Offre_Technique_{safe_client}__{mois}_{annee}.docx"

    async def build_sections(self, scoring: ScoringResult, client_name: str = "") -> tuple[dict, str, str]:
        """Étape 1 : génère (LLM) le plan de document éditable, SANS produire le .docx.
        Retourne (document {cover, blocks}, domaine, client_name enrichi)."""
        domain = _detect_domain(scoring)
        if not client_name or not client_name.strip():
            client_name = _extract_client_from_scoring(scoring)
        document = await self._generate_document(scoring, client_name, domain)
        return document, domain, client_name

    def render(
        self,
        scoring: ScoringResult,
        sections: dict,
        client_name: str = "",
        selected_cvs: list[str] | None = None,
        selected_abes: list[str] | None = None,
        kb_team: dict[str, tuple[str, str]] | None = None,
    ) -> OfferDraft:
        """Étape 2 : produit le .docx à partir du plan de document (éventuellement édité).

        `kb_team` : { fichier_source CV → (nom_complet, titre_poste) } résolu depuis
        `kb_cv` (base de connaissance GED) — le tableau équipe utilise ces vraies
        données plutôt que de deviner un nom/rôle depuis le nom de fichier."""
        if not client_name or not client_name.strip():
            client_name = _extract_client_from_scoring(scoring)
        cover = sections.get("cover") or {}
        blocks = sections.get("blocks") or []
        docx_bytes = build_offer_docx(
            cover=cover, blocks=blocks, client_name=client_name,
            selected_cvs=selected_cvs or [], selected_abes=selected_abes or [],
            kb_team=kb_team,
        )
        filename = self.build_filename(scoring, client_name)
        logger.info("Offre rendue : %s (%d bloc(s) IA)", filename, len(blocks))
        return OfferDraft(
            filename=filename,
            content_docx=docx_bytes,
            ao_filename=scoring.ao_filename,
            sections=["Couverture", "Présentation Neurones", "Corps technique",
                      "Méthodologie", "Équipe", "Certifications", "Annexes"],
        )

    async def generate(
        self,
        scoring: ScoringResult,
        client_name: str = "",
        selected_cvs: list[str] | None = None,
        selected_abes: list[str] | None = None,
    ) -> OfferDraft:
        """Flux complet (1 passe) : plan de document IA puis rendu .docx."""
        document, _domain, client = await self.build_sections(scoring, client_name)
        return self.render(scoring, document, client, selected_cvs, selected_abes)

    # ── Génération LLM ────────────────────────────────────────────────────────

    async def _generate_document(self, scoring: ScoringResult, client_name: str, domain: str) -> dict:
        delai = next(
            (e.value for e in scoring.key_elements
             if any(k in e.category.lower() for k in ("délai", "date", "remise"))),
            "non précisé",
        )
        budget = next(
            (e.value for e in scoring.key_elements
             if any(k in e.category.lower() for k in ("budget", "montant", "coût"))),
            "non précisé",
        )
        user = _offer_user_context(scoring, client_name, domain, delai, budget)
        use_premium = bool(self._llm_premium) and settings.offer_sections_model == "sonnet"
        gen_llm = self._llm_premium if use_premium else self._llm
        max_out = 12000 if use_premium else 8000
        try:
            raw = await gen_llm.generate(
                system=_build_document_system(),
                user=user, max_tokens=max_out, raise_on_truncation=True,
                temperature=0.7,  # rédaction de l'offre : créativité conservée
            )
        except OutputTruncatedError as exc:
            logger.error(
                "Plan de document TRONQUÉ au plafond de %d tokens — relève le budget si récurrent.",
                exc.max_tokens,
            )
            raw = exc.partial_text  # parse de récupération : on sauve les blocs récupérables

        document = _parse_document(raw)
        blocks = document.get("blocks") or []
        if not blocks:
            logger.warning("Plan de document illisible (%s) — repli déterministe depuis le scoring.", domain)
            return _fallback_document(scoring, client_name)
        # Couverture : complète le titre si le LLM ne l'a pas fourni.
        cover = document.get("cover") or {}
        if not cover.get("titre"):
            ao_short = scoring.ao_filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
            cover["titre"] = f"Développement d'une solution — {ao_short}"
        if not cover.get("sous_titre"):
            cover["sous_titre"] = "Offre technique"
        logger.info("Plan de document généré (%s) : %d bloc(s).", domain, len(blocks))
        return {"cover": cover, "blocks": blocks}
