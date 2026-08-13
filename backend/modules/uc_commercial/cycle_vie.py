"""Cycle de vie des affaires au-dessus du seuil — §2 du compte-rendu DC.

« Cycle de vie de l'opportunité à tracer de bout en bout, pour les opportunités à
partir de 30 millions. »

Ce module dit honnêtement ce qui est traçable et ce qui ne l'est pas, en trois
niveaux qui ne doivent jamais être confondus :

1. MESURÉ, complet — le stock d'affaires au-dessus du seuil : combien, pour quel
   montant, à quelle étape, portées par qui, depuis combien de temps ouvertes.
2. MESURÉ, partiel — la durée création → clôture, calculable sur les seules
   opportunités portant une `date_closed` (1 360 sur 9 475). Le sous-ensemble est
   annoncé avec le chiffre : une durée médiane calculée sur 14 % du volume n'est
   pas la durée médiane de l'équipe.
3. NON MESURÉ — la durée passée à CHAQUE étape. Le miroir écrase l'étape
   précédente à chaque mise à jour. Les instantanés quotidiens commencent à
   constituer l'historique : ce module lit leur profondeur réelle et le mouvement
   observé, et sert le gabarit de `statique.py` uniquement en complément, jamais
   à la place.

Le seuil est paramétrable (`commercial_params`) : le cadrage relève que « 30
millions » est employé dans le CR à la fois comme seuil et comme objectif, en
devise non tranchée. Un seuil codé en dur se lirait comme une règle validée.
"""
from __future__ import annotations

from datetime import date, datetime

from modules.uc_commercial import statique
from modules.uc_commercial.comptes import est_ouverte

# Au-delà de cette ancienneté sans clôture, une affaire est dite enlisée. 180
# jours = deux trimestres : une affaire qui traverse deux forecasts sans se
# conclure a cessé d'être une prévision.
SEUIL_ENLISEMENT_JOURS = 180


def _parse_date(valeur: str | None) -> date | None:
    if not valeur:
        return None
    try:
        return datetime.strptime(str(valeur)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _median(valeurs: list[float]) -> float:
    if not valeurs:
        return 0.0
    o = sorted(valeurs)
    m = len(o) // 2
    return float(o[m]) if len(o) % 2 else (o[m - 1] + o[m]) / 2


def _date_creation_fiable(valeur: str | None) -> date | None:
    """Écarte les dates d'IMPORT en masse, inexploitables comme dates de création.

    Deux journées concentrent 6 475 créations (07/04/2026 : 4 927 ; 02/07/2026 :
    1 548). Les retenir comme dates de création ferait apparaître des affaires de
    « 4 mois d'âge » pour des dossiers ouverts depuis des années, et rendrait
    fausse toute durée de cycle.
    """
    d = _parse_date(valeur)
    if d is None or d.isoformat() in DATES_IMPORT:
        return None
    return d


DATES_IMPORT = {"2026-04-07", "2026-07-02"}


def build_cycle_vie(
    opportunites: list[dict],
    mouvements: dict | None,
    dates_snapshots: list[str],
    seuil_xof: int | None = None,
    today: date | None = None,
    limit: int = 15,
) -> dict:
    """Traçage des affaires ≥ seuil, avec le degré de traçabilité réellement atteint."""
    jour = today or date.today()
    seuil = seuil_xof or statique.SEUIL_CYCLE_VIE_XOF

    au_dessus = [o for o in opportunites if o.get("montant_xof", 0) >= seuil]
    ouvertes = [o for o in au_dessus if est_ouverte(o.get("stage"))]
    closes = [o for o in au_dessus if not est_ouverte(o.get("stage"))]

    # ── Niveau 1 : le stock, entièrement mesuré ──────────────────────────────
    par_etape: dict[str, dict] = {}
    for o in ouvertes:
        e = par_etape.setdefault(o.get("stage") or "(étape absente)", {
            "stage": o.get("stage") or "(étape absente)", "nb": 0, "montant_xof": 0,
        })
        e["nb"] += 1
        e["montant_xof"] += o["montant_xof"]
    etapes = sorted(par_etape.values(), key=lambda e: -e["montant_xof"])

    affaires: list[dict] = []
    enlisees = 0
    for o in ouvertes:
        creee = _date_creation_fiable(o.get("creee_le"))
        age = (jour - creee).days if creee else None
        echeance = _parse_date(o.get("deadline"))
        enlisee = age is not None and age >= SEUIL_ENLISEMENT_JOURS
        if enlisee:
            enlisees += 1
        affaires.append({
            "opp_id": o.get("opp_id"),
            "name": o.get("name"),
            "client": o.get("client") or "(client non renseigné)",
            "stage": o.get("stage") or "",
            "montant_xof": o["montant_xof"],
            "probabilite_pct": o.get("probabilite_pct", 0),
            "commercial": o.get("commercial") or "",
            "deadline": o.get("deadline"),
            "echeance_depassee": bool(echeance and echeance < jour),
            "creee_le": creee.isoformat() if creee else None,
            "age_jours": age,
            "enlisee": enlisee,
            "derniere_modification": o.get("modifiee_le"),
        })
    affaires.sort(key=lambda a: -a["montant_xof"])

    # ── Niveau 2 : durée création → clôture, sur le sous-ensemble daté ───────
    durees: list[float] = []
    for o in closes:
        creee = _date_creation_fiable(o.get("creee_le"))
        close = _parse_date(o.get("close_le"))
        if creee and close and close >= creee:
            durees.append((close - creee).days)
    nb_closes_datees = len(durees)

    # ── Niveau 3 : profondeur réelle de l'historique d'étapes ────────────────
    profondeur = _profondeur_historique(dates_snapshots)
    mvt = mouvements or {"nb_suivies": 0, "changements_etape": [], "changements_montant": []}

    return {
        "as_of": jour.isoformat(),
        "seuil_xof": seuil,
        "stock": {
            "nb_total": len(au_dessus),
            "nb_ouvertes": len(ouvertes),
            "nb_closes": len(closes),
            "montant_ouvert_xof": sum(o["montant_xof"] for o in ouvertes),
            "montant_ouvert_pondere_xof": round(sum(
                o["montant_xof"] * (o.get("probabilite_pct", 0) / 100) for o in ouvertes
            )),
            "nb_enlisees": enlisees,
            "seuil_enlisement_jours": SEUIL_ENLISEMENT_JOURS,
            "part_pipe_ouvert_pct": _part(
                sum(o["montant_xof"] for o in ouvertes),
                sum(o.get("montant_xof", 0) for o in opportunites if est_ouverte(o.get("stage"))),
            ),
        },
        "par_etape": etapes,
        "affaires": affaires[:limit],
        "duree_close": {
            "source": statique.SOURCE_REELLE,
            "nb_mesurees": nb_closes_datees,
            "nb_closes_total": len(closes),
            "couverture_pct": round(100 * nb_closes_datees / len(closes), 1) if closes else 0.0,
            "mediane_jours": round(_median(durees)) if durees else None,
            "moyenne_jours": round(sum(durees) / len(durees)) if durees else None,
            # Mesuré sur ce miroir : 31 affaires datées sur 841 closes au-dessus du
            # seuil, soit 3,7 %, avec une médiane à 0 jour (création et clôture le
            # même jour, typique d'une reprise de dossier déjà conclu). Une durée
            # de cycle calculée là-dessus n'est pas la durée de cycle de l'équipe :
            # le drapeau existe pour que l'écran affiche la couverture plutôt que
            # le chiffre.
            "exploitable": nb_closes_datees >= 30 and (
                round(100 * nb_closes_datees / len(closes), 1) if closes else 0.0
            ) >= 20.0,
            "raison_non_exploitable": (
                "Trop peu d'affaires closes portent à la fois une date de création exploitable et une date "
                "de clôture : la durée calculée décrirait un échantillon, pas le cycle de vente."
            ),
        },
        "historique_etapes": {
            "source": statique.SOURCE_STATIQUE,
            "raison": statique.RAISON_CYCLE_STATIQUE,
            "avertissement": statique.AVERTISSEMENT_STATIQUE,
            "durees_par_etape": statique.DUREES_ETAPES_STATIQUE,
            "profondeur_reelle": profondeur,
            "mouvement_observe": {
                "depuis": mvt.get("depuis"),
                "jusqu_a": mvt.get("jusqu_a"),
                "nb_suivies": mvt.get("nb_suivies", 0),
                "nb_changements_etape": len(mvt.get("changements_etape", [])),
                "nb_changements_montant": len(mvt.get("changements_montant", [])),
                "changements_etape": mvt.get("changements_etape", [])[:8],
            },
        },
        "note": (
            f"Seuil de traçage : {seuil // 1_000_000} M FCFA. Le stock et sa répartition par étape sont "
            "mesurés sur la totalité du pipe. La durée création → clôture n'est calculée que sur les "
            "affaires portant une date de clôture, et les dates de création correspondant aux deux "
            "imports en masse (07/04/2026 et 02/07/2026) sont écartées : les retenir donnerait des "
            "affaires de quatre mois d'âge pour des dossiers ouverts depuis des années. La durée passée "
            "à chaque étape n'est pas mesurable en l'état."
        ),
    }


def _part(numerateur: float, denominateur: float) -> float:
    return round(100 * numerateur / denominateur, 1) if denominateur else 0.0


def _profondeur_historique(dates: list[str]) -> dict:
    """Ce que l'historique accumulé permet réellement de dire, en clair.

    Deux instantanés à quinze jours d'écart ne constituent pas un historique de
    cycle de vie ; le dire ici évite qu'un écran laisse croire le contraire.
    """
    if not dates:
        return {"nb_instantanes": 0, "premier": None, "dernier": None, "profondeur_jours": 0, "exploitable": False}
    premier, dernier = dates[0], dates[-1]
    d1, d2 = _parse_date(premier), _parse_date(dernier)
    profondeur = (d2 - d1).days if d1 and d2 else 0
    return {
        "nb_instantanes": len(dates),
        "premier": premier,
        "dernier": dernier,
        "profondeur_jours": profondeur,
        # Un trimestre d'instantanés est le minimum pour qu'une durée d'étape ait
        # un sens sur un cycle de vente qui dure plusieurs mois.
        "exploitable": profondeur >= 90 and len(dates) >= 30,
    }
