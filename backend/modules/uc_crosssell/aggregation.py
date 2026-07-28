"""Agrégation « montée en valeur » (cross-sell / up-sell / renouvellement /
obsolescence) sur les vraies lignes de commande (sale_orders.order_lines).

Remplace le classement par mots-clés sur du texte inventé (ancien
frontend/lib/valeur.ts) par un classement réel : catégorie produit détectée
par mot-clé sur le VRAI libellé produit, dates réelles de dernière commande.

Les catégories et les paires complémentaires sont une convention métier — à
valider avec la Direction Commerciale, facilement ajustable ici.
"""
from __future__ import annotations

from datetime import date, datetime

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "reseau": ["cisco", "router", "switch", "catalyst", " wan ", " lan ", "wifi", "réseau", "reseau"],
    "securite": ["fortinet", "fortigate", "firewall", "pare-feu", "f5-", "big-ip", " ips ", "waf", "sécurité", "securite", "antivirus", "forticare", "forticasb"],
    "serveurs_stockage": ["dell", "poweredge", "powerstore", "server", "serveur", "storage", "stockage", " nas ", " san "],
    "cloud_virtualisation": ["vmware", "vsan", "red hat", "openshift", "virtualisation", "cloud", "azure", "hyperviseur"],
    "licences_maintenance": ["licence", "license", "maintenance", "support", "abonnement", "subscription", "garantie"],
}

CATEGORY_LABELS: dict[str, str] = {
    "reseau": "Réseau",
    "securite": "Sécurité",
    "serveurs_stockage": "Serveurs & Stockage",
    "cloud_virtualisation": "Cloud & Virtualisation",
    "licences_maintenance": "Licences & Maintenance",
}

# Présence dans A sans aucune trace dans B = opportunité de cross-sell.
COMPLEMENTARY_PAIRS: list[tuple[str, str]] = [
    ("reseau", "securite"),
    ("serveurs_stockage", "cloud_virtualisation"),
]

_RENOUVELLEMENT_MIN_MOIS = 6
_RENOUVELLEMENT_MAX_MOIS = 20
_OBSOLETE_MIN_MOIS = 24
_UP_SELL_MIN_XOF = 10_000_000  # 10 M FCFA — en dessous, signal trop faible pour être actionnable


def _classify(product: str | None) -> str | None:
    p = f" {(product or '').lower()} "
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in p for kw in keywords):
            return cat
    return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _months_since(d: date, today: date) -> int:
    return (today.year - d.year) * 12 + (today.month - d.month)


def _m_fcfa(xof: float) -> int:
    return round(xof / 1_000_000)


def build_montee_valeur(lines: list[dict]) -> dict:
    """lines : sortie de CRMRepository.get_order_lines() (champs réels)."""
    today = date.today()

    # client_id -> categorie -> {total_xof, last_date, nb_lignes}
    by_client: dict[str, dict[str, dict]] = {}
    client_names: dict[str, str] = {}

    for line in lines:
        cat = _classify(line["product"])
        if cat is None:
            continue
        d = _parse_date(line["date_order"])
        if d is None:
            continue
        cid = line["client_id"] or line["client"]
        client_names[cid] = line["client"]
        bucket = by_client.setdefault(cid, {})
        entry = bucket.setdefault(cat, {"total_xof": 0.0, "last_date": d})
        entry["total_xof"] += line["subtotal_xof"] or 0
        if d > entry["last_date"]:
            entry["last_date"] = d

    renouvellement: list[dict] = []
    obsolete: list[dict] = []
    cross_sell: list[dict] = []
    up_sell: list[dict] = []

    for cid, categories in by_client.items():
        client = client_names[cid]

        for cat, info in categories.items():
            age_mois = _months_since(info["last_date"], today)
            label = CATEGORY_LABELS[cat]
            montant_m = _m_fcfa(info["total_xof"])
            mois_annee = info["last_date"].strftime("%m/%Y")

            if _RENOUVELLEMENT_MIN_MOIS <= age_mois <= _RENOUVELLEMENT_MAX_MOIS:
                renouvellement.append({
                    "client": client,
                    "titre": label,
                    "detail": (
                        f"{montant_m} M FCFA investis, dernière commande en {mois_annee}, soit "
                        f"{age_mois} mois — échéance de renouvellement probable (cycle annuel)."
                    ),
                    "montant_xof": round(info["total_xof"]),
                    "age_mois": age_mois,
                })
            elif age_mois > _OBSOLETE_MIN_MOIS:
                obsolete.append({
                    "client": client,
                    "titre": label,
                    "detail": (
                        f"{montant_m} M FCFA investis, dernière commande en {mois_annee}, soit "
                        f"{age_mois} mois — probablement en fin de cycle technologique, à réévaluer."
                    ),
                    "montant_xof": round(info["total_xof"]),
                    "age_mois": age_mois,
                })

        for cat_a, cat_b in COMPLEMENTARY_PAIRS:
            has_a, has_b = cat_a in categories, cat_b in categories
            if has_a and not has_b:
                actuelle, opportunite, montant = cat_a, cat_b, categories[cat_a]["total_xof"]
            elif has_b and not has_a:
                actuelle, opportunite, montant = cat_b, cat_a, categories[cat_b]["total_xof"]
            else:
                continue
            cross_sell.append({
                "client": client,
                "titre": CATEGORY_LABELS[opportunite],
                "detail": (
                    f"{_m_fcfa(montant)} M FCFA investis en {CATEGORY_LABELS[actuelle]}, aucun achat "
                    f"en {CATEGORY_LABELS[opportunite]} à ce jour — opportunité de vente croisée."
                ),
                "montant_xof": round(montant),
            })

        if len(categories) == 1:
            (only_cat, info), = categories.items()
            if info["total_xof"] >= _UP_SELL_MIN_XOF:
                up_sell.append({
                    "client": client,
                    "titre": CATEGORY_LABELS[only_cat],
                    "detail": (
                        f"{_m_fcfa(info['total_xof'])} M FCFA concentrés sur "
                        f"{CATEGORY_LABELS[only_cat]} uniquement — potentiel de diversification "
                        "vers d'autres catégories."
                    ),
                    "montant_xof": round(info["total_xof"]),
                })

    def _top(items: list[dict], limit: int = 20) -> list[dict]:
        return sorted(items, key=lambda x: x["montant_xof"], reverse=True)[:limit]

    return {
        "renouvellement": _top(renouvellement),
        "obsolete": _top(obsolete),
        "cross_sell": _top(cross_sell),
        "up_sell": _top(up_sell),
    }
