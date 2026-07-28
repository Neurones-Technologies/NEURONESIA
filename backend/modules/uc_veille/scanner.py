import logging
import re
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

_BUDGET_RE = re.compile(r'(\d[\d\s,.]*(?:millions?|milliards?|FCFA|XOF|CFA|MXOF))', re.IGNORECASE)
_DEADLINE_RE = re.compile(
    r'(?:date\s+limite|délai|remise|dépôt)\s*[:\-]?\s*([\d/\-\.]+\s*(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)?(?:\s+\d{4})?)',
    re.IGNORECASE,
)

DEMO_SOURCES = [
    {
        "name": "DGMP Côte d'Ivoire",
        "url": "https://www.dgmp.gouv.ci/fr/avis-appels-offres",
        "feed_type": "html",
        "keywords": "informatique,développement,infrastructure,système,réseau,logiciel,IT,digital,numérique",
    },
    {
        "name": "BOAD Appels d'Offres",
        "url": "https://www.boad.org/appels-doffres/",
        "feed_type": "html",
        "keywords": "informatique,système d'information,réseau,infrastructure",
    },
]


def extract_budget(text: str) -> str:
    m = _BUDGET_RE.search(text)
    return m.group(1).strip() if m else ""


def extract_deadline(text: str) -> str:
    m = _DEADLINE_RE.search(text)
    return m.group(1).strip() if m else ""


def score_relevance(text: str, keywords: str) -> int:
    if not keywords:
        return 50
    kws = [k.strip().lower() for k in keywords.split(",") if k.strip()]
    text_lower = text.lower()
    matches = sum(1 for k in kws if k in text_lower)
    return min(100, int((matches / max(len(kws), 1)) * 100) + 30)


async def scan_rss_feed(url: str, keywords: str = "") -> list[dict]:
    """Scanne un flux RSS/Atom et retourne les entrées."""
    try:
        import feedparser
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "NeuropeIA-Veille/1.0"})
            response.raise_for_status()
        feed = feedparser.parse(response.text)
        entries = []
        for entry in feed.entries[:20]:
            title = getattr(entry, "title", "")
            desc = getattr(entry, "summary", "") or getattr(entry, "description", "")
            link = getattr(entry, "link", "")
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6])
            full_text = f"{title} {desc}"
            entries.append({
                "title": title[:500],
                "url": link[:500],
                "description": desc[:2000],
                "published_at": published,
                "estimated_budget": extract_budget(full_text),
                "deadline": extract_deadline(full_text),
                "relevance_score": score_relevance(full_text, keywords),
            })
        return entries
    except Exception as e:
        logger.warning(f"Erreur scan RSS {url}: {e}")
        return []


async def scan_html_page(url: str, keywords: str = "") -> list[dict]:
    """Scanne une page HTML et tente d'extraire des AOs."""
    from urllib.parse import urljoin
    try:
        from bs4 import BeautifulSoup
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0 NeuropeIA/1.0"})
            response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        def _abs(href: str) -> str:
            if not href:
                return ""
            href = href.strip()
            if href.startswith(("http://", "https://")):
                return href
            if href.startswith("javascript:") or href.startswith("#"):
                return ""
            return urljoin(url, href)

        def _best_href(tag) -> str:
            """Cherche le meilleur lien : la balise elle-même, ou le premier <a> enfant."""
            if tag.name == "a":
                return _abs(tag.get("href", ""))
            # Chercher <a> à l'intérieur (ex: <li><a href="...">titre</a></li>)
            child_a = tag.find("a", href=True)
            if child_a:
                return _abs(child_a.get("href", ""))
            return ""

        _AO_KWS = ["appel", "offre", "marché", "avis", "consultation", "tender", "avis d'appel", "dao"]
        entries = []
        seen_urls: set[str] = set()

        for tag in soup.find_all(["a", "li", "tr", "div", "article"], limit=200):
            text = tag.get_text(separator=" ", strip=True)
            if len(text) < 20 or len(text) > 800:
                continue
            if not any(k in text.lower() for k in _AO_KWS):
                continue

            href = _best_href(tag)
            # Éviter les doublons dans ce scan
            dedup_key = href or text[:80]
            if dedup_key in seen_urls:
                continue
            seen_urls.add(dedup_key)

            entries.append({
                "title": text[:500],
                "url": href[:500],
                "description": text[:2000],
                "published_at": None,
                "estimated_budget": extract_budget(text),
                "deadline": extract_deadline(text),
                "relevance_score": score_relevance(text, keywords),
            })
            if len(entries) >= 25:
                break
        return entries
    except Exception as e:
        logger.warning(f"Erreur scan HTML {url}: {e}")
        return []
