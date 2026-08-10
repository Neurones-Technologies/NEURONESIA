"""Agrégation du mix d'offre du pipeline : répartition par famille et évolution.

Répond à la question du Directeur Commercial « comment se répartit mon pipeline
entre logiciel, réseau, équipement et services, et comment ça bouge ». Fonction
pure sur des dicts, comme `build_pipeline_forecast` (modules/uc_forecast) et
`build_montee_valeur` (modules/uc_crosssell) — testable sans base.

Deux partis pris qui distinguent ce module des autres agrégations du cockpit :

1. LE NON-CLASSÉ EST COMPTÉ, JAMAIS JETÉ. Le cross-sell fait `continue` sur les
   lignes qu'il ne sait pas classer (acceptable : il cherche des signaux, pas des
   parts). Ici les parts DOIVENT être défendables : elles sont calculées sur le
   total classé, et `coverage` dit sur quelle fraction du pipe elles portent.
   Sans ça, « Réseau 33 % » se lirait comme 33 % du pipe alors que c'est 33 % de
   81 % du pipe.

2. LES ÉTAPES SONT NORMALISÉES PAR MOTIF, pas par égalité. Le référentiel Odoo
   porte 16 valeurs distinctes pour ~9 étapes réelles : deux nomenclatures
   coexistent (« 6-Gagné » / « Won », « 1-Qualification » / « Qualified ») et des
   doublons par espace parasite (« 8-Suspendu » 682 vs « 8- Suspendu » 55).
   Comparer `stage == "6-Gagné"` perdrait silencieusement 681 affaires gagnées.
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime

from modules.uc_offermix.taxonomy import FAMILY_ORDER, classify_family, label_of

# Motifs de détection des étapes closes, appliqués sur le stage normalisé
# (minuscules, sans accent, espaces réduits). Volontairement des SOUS-CHAÎNES :
# « gagn » couvre « 6-Gagné », « Gagnée », « Won » est couvert à part.
_WON_PATTERNS = ("gagn", "won")
_LOST_PATTERNS = ("perdu", "lost")
_CANCELLED_PATTERNS = ("annul", "cancel")

# Garde-fous du delta de part entre deux trimestres. Un delta n'est publiable que
# si les deux trimestres sont assez fournis ET assez diversifiés :
#  - le volume seul ne suffit pas : sur ce pipe, le trimestre courant porte 65
#    opportunités mais UNE SEULE affaire y fait 78 % du montant, ce qui produit un
#    « -16,7 pt » qui ne mesure que cette affaire ;
#  - d'où le second test : si la plus grosse opportunité pèse plus de la moitié du
#    trimestre, la part est portée par un cas isolé et le delta n'est pas un signal.
_MIN_OPPS_FOR_DELTA = 30
_MAX_TOP_DEAL_SHARE_FOR_DELTA = 50.0


def _normalize_stage(stage: str | None) -> str:
    """Minuscules, sans accent, espaces réduits — pour comparer par motif."""
    if not stage:
        return ""
    decomposed = unicodedata.normalize("NFKD", stage.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.replace("-", " ").split())


def _stage_outcome(stage: str | None) -> str:
    """Sort du référentiel doublonné : "won" / "lost" / "cancelled" / "open"."""
    s = _normalize_stage(stage)
    if any(p in s for p in _WON_PATTERNS):
        return "won"
    if any(p in s for p in _LOST_PATTERNS):
        return "lost"
    if any(p in s for p in _CANCELLED_PATTERNS):
        return "cancelled"
    return "open"


def _parse_date(value: str | None) -> date | None:
    """Même tolérance que les autres agrégations : on ne lit que les 10 premiers
    caractères, le miroir stocke tantôt une date, tantôt un datetime."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _quarter_index(d: date) -> int:
    """Trimestre exprimé en index absolu (année × 4 + trimestre), pour pouvoir
    reculer d'un trimestre sans gérer les passages d'année à la main."""
    return d.year * 4 + (d.month - 1) // 3


def _quarter_label_from_index(idx: int) -> str:
    return f"{idx // 4}-T{idx % 4 + 1}"


def _window_quarter_indexes(today: date, nb_past: int, nb_future: int) -> list[int]:
    """Fenêtre trimestrielle CALENDAIRE continue autour du trimestre courant.

    L'axe porte des ÉCHÉANCES : il regarde donc devant (ce qui reste à atterrir)
    autant que derrière (ce qui aurait dû l'être). Le trimestre courant est
    inclus.

    Grille continue, et non « les N trimestres où il y a de la donnée » :
    juxtaposer des trimestres non consécutifs ferait lire des variations qui ne
    sont qu'un artefact d'axe, et comparer deux périodes distantes de trois ans
    pour en tirer une tendance.
    """
    current = _quarter_index(today)
    return list(range(current - nb_past, current + nb_future + 1))


def _pct(part: float, whole: float) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def build_offer_mix(
    opportunities: list[dict],
    today: date | None = None,
    nb_past_periods: int = 5,
    nb_future_periods: int = 2,
) -> dict:
    """Mix d'offre du pipeline, par famille et par trimestre.

    `opportunities` : dicts au contrat de `CRMRepository.list_all_opportunities()`
    — clés `opportunite`, `client`, `stade`, `revenu_attendu_xof`,
    `probabilite_pct`, `commercial`, `creee_le`, et `famille` si déjà persistée
    (sinon reclassée ici depuis le libellé).

    `today` : ancre de la grille trimestrielle, injectable pour rendre les tests
    déterministes (défaut : date du jour).

    `nb_past_periods` / `nb_future_periods` : largeur de la fenêtre trimestrielle
    autour du trimestre courant. L'axe porte des ÉCHÉANCES : il regarde devant
    (ce qui reste à atterrir) autant que derrière (ce qui aurait dû l'être).

    Le périmètre diffère selon la mesure, volontairement :
    - familles / couverture / évolution → pipeline OUVERT (une affaire close ne
      dit plus rien du positionnement commercial en cours) ;
    - taux de réussite → affaires CLOSES uniquement (gagné vs perdu), seul
      périmètre où « réussite » a un sens.
    """
    today = today or date.today()
    open_rows: list[dict] = []
    closed_rows: list[dict] = []

    for o in opportunities:
        # `famille` peut arriver pré-calculée du miroir (colonne offer_family) ;
        # à défaut on classe à la volée — le résultat doit être identique.
        family = o.get("famille") or classify_family(o.get("opportunite"))
        value = o.get("revenu_attendu_xof") or 0
        prob = o.get("probabilite_pct") or 0
        row = {
            "family": family,
            "value_xof": value,
            "weighted_xof": value * prob / 100,
            # Axe temporel = ÉCHÉANCE, pas création. `creee_le` est inexploitable
            # dans le miroir : 4 926 opportunités sur 6 675 portent la même date
            # (2026-04-07, un import en masse), ce qui produirait un pic
            # artificiel sur un seul trimestre. `deadline` est renseignée à 96 %
            # et se répartit continûment de 2024-T2 à 2026-T4.
            "echeance": _parse_date(o.get("deadline")),
        }
        outcome = _stage_outcome(o.get("stade"))
        if outcome == "open":
            open_rows.append(row)
        elif outcome in ("won", "lost"):
            closed_rows.append({**row, "won": outcome == "won"})
        # "cancelled" : ni pipeline vivant, ni résultat commercial — écarté des
        # deux périmètres, mais compté dans `nb_annulees` pour que le total soit
        # rapprochable du nombre d'opportunités de la base.

    # ── Taux de réussite par famille (sur les closes) ─────────────────────────
    win: dict[str, dict[str, float]] = {
        f: {"won": 0, "total": 0, "won_xof": 0.0, "total_xof": 0.0} for f in FAMILY_ORDER
    }
    for r in closed_rows:
        if r["family"] not in win:
            continue
        bucket = win[r["family"]]
        bucket["total"] += 1
        bucket["total_xof"] += r["value_xof"]
        if r["won"]:
            bucket["won"] += 1
            bucket["won_xof"] += r["value_xof"]

    # ── Familles sur le pipeline ouvert ───────────────────────────────────────
    classified = [r for r in open_rows if r["family"] in win]
    unclassified = [r for r in open_rows if r["family"] not in win]

    montant_classe = sum(r["value_xof"] for r in classified)
    nb_classe = len(classified)
    montant_total = montant_classe + sum(r["value_xof"] for r in unclassified)
    nb_total = nb_classe + len(unclassified)

    families = []
    for family in FAMILY_ORDER:
        rows = [r for r in classified if r["family"] == family]
        montant = sum(r["value_xof"] for r in rows)
        w = win[family]
        families.append({
            "family": family,
            "label": label_of(family),
            "nb": len(rows),
            "montant_xof": round(montant),
            "montant_pondere_xof": round(sum(r["weighted_xof"] for r in rows)),
            # Parts sur le CLASSÉ : c'est ce que le graphe montre, et `coverage`
            # dit sur quelle fraction du pipe ces parts portent.
            "part_montant_pct": _pct(montant, montant_classe),
            "part_nb_pct": _pct(len(rows), nb_classe),
            # Taux de réussite en valeur (cohérent avec le « taux de victoire »
            # déjà affiché sur la vue DC, calculé lui aussi en valeur).
            "win_rate_pct": _pct(w["won_xof"], w["total_xof"]),
            "nb_closes": int(w["total"]),
        })
    families.sort(key=lambda f: f["montant_xof"], reverse=True)

    # ── Mix d'atterrissage par trimestre d'échéance ───────────────────────────
    # ATTENTION à la lecture : ceci ventile le pipeline ouvert AUJOURD'HUI par sa
    # date de clôture PRÉVUE. Ce n'est donc pas une tendance mesurée mais une
    # projection, à deux réserves près :
    #  - les opportunités closes ou supprimées n'y sont pas (biais de survivance) ;
    #  - une échéance est déclarative et bouge (cf. les affaires à échéance déjà
    #    dépassée, marquées `echu`).
    # La vraie courbe historique viendra des snapshots quotidiens
    # (table pipeline_snapshots), d'où le drapeau `historique_reel: False`.
    by_quarter: dict[int, dict[str, dict[str, float]]] = {}
    # Plus grosse opportunité de chaque trimestre : sert à mesurer la
    # concentration, qui décide si un delta de part est publiable.
    top_deal_by_quarter: dict[int, float] = {}
    for r in classified:
        if r["echeance"] is None:
            continue
        idx = _quarter_index(r["echeance"])
        q = by_quarter.setdefault(idx, {})
        entry = q.setdefault(r["family"], {"nb": 0, "montant_xof": 0.0})
        entry["nb"] += 1
        entry["montant_xof"] += r["value_xof"]
        top_deal_by_quarter[idx] = max(top_deal_by_quarter.get(idx, 0.0), r["value_xof"])

    window = _window_quarter_indexes(today, nb_past_periods, nb_future_periods)
    current_idx = _quarter_index(today)
    periods = []
    for idx in window:
        bucket = by_quarter.get(idx, {})
        total_q = sum(e["montant_xof"] for e in bucket.values())
        nb_q = sum(int(e["nb"]) for e in bucket.values())
        top_deal_share = _pct(top_deal_by_quarter.get(idx, 0.0), total_q)
        periods.append({
            "period": _quarter_label_from_index(idx),
            "montant_total_xof": round(total_q),
            "nb_total": nb_q,
            # Un trimestre sans échéance n'est pas une anomalie : le pipe se
            # renouvelle. Le front doit pouvoir l'afficher à zéro sans le
            # confondre avec une absence de mesure.
            "vide": nb_q == 0,
            # Échéance déjà passée : ces affaires pèsent encore dans le pipe mais
            # leur date n'a pas été tenue à jour. La vue DC porte déjà cette
            # lecture (tuile « Opportunités à requalifier ») — la reprendre ici
            # évite qu'un trimestre passé bien garni se lise comme du forecast.
            "echu": idx < current_idx,
            "courant": idx == current_idx,
            # Poids de la plus grosse affaire du trimestre. Au-delà de ~50 %, la
            # répartition du trimestre raconte cette affaire, pas un mix.
            "concentration_top_deal_pct": top_deal_share,
            "families": [
                {
                    "family": f,
                    "label": label_of(f),
                    "nb": int(bucket.get(f, {}).get("nb", 0)),
                    "montant_xof": round(bucket.get(f, {}).get("montant_xof", 0.0)),
                    "part_montant_pct": _pct(bucket.get(f, {}).get("montant_xof", 0.0), total_q),
                }
                for f in FAMILY_ORDER
            ],
        })

    # Hors grille : échéances antérieures à la fenêtre, postérieures à la fenêtre,
    # ou absentes. Il faut les exposer, sinon la somme des trimestres affichés ne
    # se rapproche pas du montant classé et l'écart passe pour une erreur de
    # calcul. Les échéances manquantes sont un défaut de saisie à part entière.
    first_idx, last_idx = window[0], window[-1]
    hors_fenetre = [
        r for r in classified
        if r["echeance"] is not None and not (first_idx <= _quarter_index(r["echeance"]) <= last_idx)
    ]
    sans_echeance = [r for r in classified if r["echeance"] is None]
    echu_rows = [r for r in classified if r["echeance"] is not None and r["echeance"] < today]

    dominante = families[0] if families and families[0]["nb"] else None
    delta_dominante_pct = None
    if dominante:
        # Delta entre le trimestre COURANT et le précédent, et seulement si les
        # deux sont alimentés. Comparer les deux derniers trimestres *avec
        # données* produirait une variation entre périodes distantes de plusieurs
        # années — c'est le piège que la grille calendaire évite.
        def _part(period: dict) -> float:
            match = next((f for f in period["families"] if f["family"] == dominante["family"]), None)
            return match["part_montant_pct"] if match else 0.0

        cur = next((p for p in periods if p["courant"]), None)
        cur_pos = periods.index(cur) if cur else -1
        if cur_pos > 0:
            prev = periods[cur_pos - 1]
            # Les DEUX trimestres doivent être assez fournis ET assez diversifiés.
            assez_fourni = min(cur["nb_total"], prev["nb_total"]) >= _MIN_OPPS_FOR_DELTA
            assez_diversifie = max(
                cur["concentration_top_deal_pct"], prev["concentration_top_deal_pct"]
            ) <= _MAX_TOP_DEAL_SHARE_FOR_DELTA
            if assez_fourni and assez_diversifie:
                delta_dominante_pct = round(_part(cur) - _part(prev), 1)

    return {
        "families": families,
        "coverage": {
            "nb_total": nb_total,
            "nb_classe": nb_classe,
            "nb_non_classe": len(unclassified),
            "couverture_nb_pct": _pct(nb_classe, nb_total),
            "montant_total_xof": round(montant_total),
            "montant_classe_xof": round(montant_classe),
            "montant_non_classe_xof": round(montant_total - montant_classe),
            "couverture_montant_pct": _pct(montant_classe, montant_total),
        },
        "periods": periods,
        "axe_temporel": "echeance",
        "hors_fenetre": {
            "nb": len(hors_fenetre),
            "montant_xof": round(sum(r["value_xof"] for r in hors_fenetre)),
        },
        "sans_echeance": {
            "nb": len(sans_echeance),
            "montant_xof": round(sum(r["value_xof"] for r in sans_echeance)),
        },
        # Part du pipe classé dont l'échéance est déjà passée. Sur ce pipe c'est
        # la majorité : la « projection d'atterrissage » porte donc surtout des
        # affaires à requalifier, ce que le front doit dire au lieu de les
        # présenter comme du forecast.
        "echu": {
            "nb": len(echu_rows),
            "montant_xof": round(sum(r["value_xof"] for r in echu_rows)),
            "part_montant_pct": _pct(sum(r["value_xof"] for r in echu_rows), montant_classe),
        },
        "dominante": {
            "family": dominante["family"] if dominante else None,
            "label": dominante["label"] if dominante else None,
            "part_montant_pct": dominante["part_montant_pct"] if dominante else 0.0,
            "delta_part_pct": delta_dominante_pct,
        },
        # `historique_reel` = False tant que la tendance est reconstruite depuis
        # les dates de création plutôt que lue dans les snapshots. Le front doit
        # s'en servir pour ne pas présenter une photo comme une évolution.
        "historique_reel": False,
        "nb_closes": len(closed_rows),
        "nb_annulees": len(opportunities) - len(open_rows) - len(closed_rows),
    }
