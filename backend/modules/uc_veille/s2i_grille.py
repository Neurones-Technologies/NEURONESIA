"""Grille de correspondance S2I Watch-Tracker — signal → risque → offre.

Source de vérité côté backend (portée depuis frontend/lib/watch-tracker.ts).
Sert à deux choses :
  1. Référence injectée dans le prompt Claude (modules/uc_veille/classifier.py) ;
  2. Repli déterministe par mots-clés quand Claude est indisponible/désactivé.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Priorités possibles + ordre de tri (0 = plus prioritaire).
PRIORITY_ORDER = {"CRITIQUE": 0, "ELEVEE": 1, "MOYENNE": 2}


@dataclass(frozen=True)
class S2IRule:
    id: str
    signal_label: str      # « Signal détecté en CI »
    risque: str            # « Risque client associé »
    offre: str             # offre S2I (texte complet)
    offre_short: str       # étiquette courte (badge), ex. « SD-WAN »
    priority: str          # CRITIQUE | ELEVEE | MOYENNE
    keywords: tuple[str, ...]  # déclencheurs (titre + description, sans accents)


# L'ordre compte : la première règle qui matche gagne (repli mots-clés).
S2I_GRILLE: list[S2IRule] = [
    S2IRule(
        id="fibre-travaux",
        signal_label="Grands travaux routiers à Abidjan (métro, échangeurs)",
        risque="Coupures fréquentes de la fibre optique par arrachement de câbles.",
        offre="Solutions SD-WAN multi-liens avec failover automatique 4G/5G / Faisceau hertzien.",
        offre_short="SD-WAN",
        priority="CRITIQUE",
        keywords=(
            "travaux", "metro", "echangeur", "voirie", "route", "chantier",
            "fibre", "cable", "arrachement", "pont", "terrassement", "genie civil",
        ),
    ),
    S2IRule(
        id="nouveau-dsi",
        signal_label="Nouveau Directeur des Systèmes d'Information (DSI) nommé",
        risque="Audit technique et renégociation des anciens contrats de l'ex-DSI.",
        offre="Audit Flash & Conseil (optimisation SI, audit sécurité de l'infrastructure).",
        offre_short="Audit Flash",
        priority="ELEVEE",
        keywords=(
            "dsi", "directeur des systemes", "directeur informatique", "nomination",
            "nomme", "nommee", "prise de fonction", "nouveau directeur", "cio",
        ),
    ),
    S2IRule(
        id="poste-vacant",
        signal_label="Offre d'emploi IT vacante depuis plus de 2 mois",
        risque="Surcharge interne, défaillances de maintenance opérationnelle.",
        offre="Services Managés / NOC as a Service (externalisation du monitoring).",
        offre_short="Services Managés",
        priority="MOYENNE",
        keywords=(
            "recrute", "recrutement", "offre d'emploi", "poste", "vacant", "vacance",
            "administrateur reseau", "admin reseau", "ingenieur", "technicien", "cdi", "emploi",
        ),
    ),
    S2IRule(
        id="cyber-artci",
        signal_label="Incident cyber sous-régional ou directive stricte de l'ARTCI",
        risque="Pertes financières massives, amendes de non-conformité réglementaire.",
        offre="Sauvegarde Hybride & PRA (Plan de Reprise d'Activité) / SOC managé.",
        offre_short="PRA / SOC",
        priority="CRITIQUE",
        keywords=(
            "cyber", "artci", "incident", "ransomware", "rancongiciel", "faille",
            "attaque", "piratage", "fuite de donnees", "conformite", "reglementaire",
            "directive", "securite", "cnil", "rgpd",
        ),
    ),
]

# Repli quand aucun signal de la grille n'est reconnu.
FALLBACK_RULE = S2IRule(
    id="a-qualifier",
    signal_label="Signal à qualifier",
    risque="Besoin client non encore caractérisé — qualification commerciale requise.",
    offre="Conseil SI & cadrage d'opportunité.",
    offre_short="À qualifier",
    priority="MOYENNE",
    keywords=(),
)

_RULES_BY_ID = {r.id: r for r in S2I_GRILLE}


def rule_by_id(rule_id: str) -> S2IRule | None:
    return _RULES_BY_ID.get(rule_id)


def normalize(s: str) -> str:
    """Minuscules + suppression des accents (miroir du normalize() front)."""
    s = (s or "").lower()
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def classify_by_keywords(title: str, description: str) -> S2IRule:
    """Repli déterministe : première règle dont un mot-clé apparaît dans le texte."""
    haystack = normalize(f"{title} {description}")
    for rule in S2I_GRILLE:
        if any(kw in haystack for kw in rule.keywords):
            return rule
    return FALLBACK_RULE


def grille_for_prompt() -> str:
    """Rend la grille en texte compact pour l'injecter dans le prompt Claude."""
    lines = []
    for r in S2I_GRILLE:
        lines.append(
            f"- id={r.id} | priorité={r.priority} | signal=\"{r.signal_label}\" "
            f"| risque=\"{r.risque}\" | offre=\"{r.offre}\" | offre_courte=\"{r.offre_short}\""
        )
    return "\n".join(lines)
