"""
Classifieur de domaine technique (UC10 Pre-Sales).

4 domaines : Digitalisation, Infrastructure, Cybersécurité, Cloud.
Approche = matching par mots-clés SCORÉ (pas binaire) :
  - normalisation accents/casse → robuste à « Cybersécurité » vs « cybersecurite » ;
  - matching sur FRONTIÈRE DE MOT (\b) → évite les faux positifs de sous-chaîne
    (« api » dans « rapide », « soc » dans « société »…) ;
  - score = nombre de mots-clés DISTINCTS trouvés par domaine ;
  - DOMAINE = TAG MULTI-VALEUR : on renvoie tous les domaines touchés, classés ;
  - bucket « Non classé » quand aucun mot-clé ne matche (jamais d'exception).

Source UNIQUE de `_DOMAIN_KEYWORDS` (offer_generator l'importe d'ici). La sortie
alimente `Exigence.domaines_suggeres` ; la correction humaine vit dans
`Exigence.domaine_valide` — l'écart suggéré/validé mesure la précision dans le temps.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from core.domain.requirements import DOMAINE_NON_CLASSE

# Domaine par défaut quand une VUE exige un domaine unique (ex: choix du template
# Word) mais qu'aucun mot-clé n'a matché. Ne s'applique JAMAIS à la matrice
# (qui, elle, conserve « Non classé » pour signaler l'exigence à classer).
DEFAULT_DOMAIN = "Digitalisation"

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "Digitalisation": [
        "application", "applications", "mobile", "web", "digital", "digitalisation",
        "plateforme", "logiciel", "développement", "saas", "api", "portail",
        "erp", "crm", "applicatif", "progiciel", "solution informatique",
        "site internet", "dématérialisation", "ged",
    ],
    "Infrastructure": [
        "réseau", "infrastructure", "serveur", "serveurs", "switch", "routeur",
        "lan", "wan", "data center", "datacenter", "équipement", "équipements",
        "fibre", "câblage", "onduleur", "baie", "stockage", "san", "nas",
    ],
    "Cybersécurité": [
        "sécurité", "cybersécurité", "firewall", "pare-feu", "siem", "soc",
        "pentest", "audit sécurité", "edr", "antivirus", "vulnérabilité",
        "iso 27001", "rgpd", "chiffrement", "authentification",
    ],
    "Cloud": [
        "cloud", "aws", "azure", "gcp", "migration cloud", "hébergement",
        "virtualisation", "conteneur", "conteneurs", "docker", "kubernetes",
        "iaas", "paas", "saas cloud",
    ],
}


@dataclass
class DomainScore:
    """Score d'un domaine pour un texte : nombre de mots-clés distincts touchés."""
    domaine: str
    score: int = 0                                   # nb de mots-clés distincts matchés
    confidence: float = 0.0                          # part relative parmi tous les hits (0–1)
    matched: list[str] = field(default_factory=list)  # mots-clés ayant matché (pour debug/traçabilité)


def _normalize(text: str) -> str:
    """Minuscule + suppression des accents (NFKD → on retire les marques combinantes).

    Le matching se fait ensuite en ASCII : les mots-clés sont normalisés de la
    même façon, donc « Cybersécurité » et « cybersecurite » sont équivalents.
    """
    nfkd = unicodedata.normalize("NFKD", text or "")
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return no_accents.lower()


# Cache des regex compilées par mot-clé normalisé (frontières de mot).
_KEYWORD_RE_CACHE: dict[str, re.Pattern] = {}


def _keyword_re(keyword_norm: str) -> re.Pattern:
    rx = _KEYWORD_RE_CACHE.get(keyword_norm)
    if rx is None:
        # \b en bord de chaque token ; un mot-clé multi-mots (« data center ») est
        # matché comme phrase, espaces internes échappés via re.escape.
        rx = re.compile(r"\b" + re.escape(keyword_norm) + r"\b")
        _KEYWORD_RE_CACHE[keyword_norm] = rx
    return rx


def classify(text: str) -> list[DomainScore]:
    """Score chaque domaine touché par `text`, classé par score décroissant.

    Retourne uniquement les domaines avec au moins un mot-clé (score ≥ 1). Liste
    vide si aucun domaine n'est touché (l'appelant décide alors du repli).
    `confidence` = part du score du domaine sur le total des hits (désambiguïse
    le multi-domaine : 3 hits Cloud / 1 hit Cyber → Cloud plus confiant).
    """
    norm = _normalize(text)
    scores: list[DomainScore] = []
    for domaine, keywords in DOMAIN_KEYWORDS.items():
        matched: list[str] = []
        for kw in keywords:
            if _keyword_re(_normalize(kw)).search(norm):
                matched.append(kw)
        if matched:
            scores.append(DomainScore(domaine=domaine, score=len(matched), matched=matched))

    total = sum(s.score for s in scores)
    for s in scores:
        s.confidence = round(s.score / total, 3) if total else 0.0
    scores.sort(key=lambda s: s.score, reverse=True)
    return scores


def suggested_domains(text: str, max_domains: int = 3) -> tuple[list[str], float]:
    """Domaines suggérés (multi-valeur) + confiance du domaine primaire.

    Politique : tous les domaines touchés (score ≥ 1), classés par score, plafonnés
    à `max_domains`. Aucun hit → (["Non classé"], 0.0). Volontairement inclusif :
    le classifieur par mots-clés est un premier jet, l'humain tranche via
    `domaine_valide` et l'écart se mesure dans le temps.
    """
    scores = classify(text)
    if not scores:
        return [DOMAINE_NON_CLASSE], 0.0
    primary_conf = scores[0].confidence
    return [s.domaine for s in scores[:max_domains]], primary_conf


def primary_domain(text: str) -> str:
    """Domaine UNIQUE pour les vues qui n'en acceptent qu'un (ex: choix du template
    Word). Argmax des scores ; `DEFAULT_DOMAIN` si aucun mot-clé ne matche."""
    scores = classify(text)
    return scores[0].domaine if scores else DEFAULT_DOMAIN
