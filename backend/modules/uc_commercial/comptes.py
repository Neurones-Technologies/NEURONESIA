"""Animation de compte : quels comptes vendent, lesquels s'emballent, lesquels arrivent.

Répond aux §1 et §2 du compte-rendu DC. Fonctions pures sur des dicts, `today`
injecté — même forme que `uc_dormance.build_suivi_dormance`.

Deux partis pris structurants :

1. QUANTITÉ ET MONTANT NE SE RÉSUMENT PAS L'UN À L'AUTRE. Le DC l'a demandé
   explicitement : « ces indicateurs doivent être restitués en quantité et en
   montant simultanément — l'un des deux seuls ne suffit pas à qualifier un
   compte ». Le classement expose donc les quatre mesures brutes (CA réalisé,
   nombre de commandes, pipe à venir, nombre d'opportunités à venir) et un indice
   qui les combine par RANG, jamais par somme : additionner des francs et des
   unités ne veut rien dire. `ecart_lecture` signale les comptes dont le rang en
   quantité et le rang en montant divergent — précisément les comptes qu'une
   lecture à une seule dimension aurait mal jugés.

2. UN PIC SE MESURE CONTRE LE PASSÉ DU COMPTE, PAS DANS L'ABSOLU. Un compte qui
   commande 200 M quand il en commande 180 d'habitude ne fait pas un pic ; un
   compte à 40 M qui saute à 150 M, oui. Le seuil est donc un multiple de la
   médiane mensuelle du compte lui-même.

Ce que ce module NE PEUT PAS voir, et qui doit rester dit à l'écran : le pic par
SOLLICITATION (demandes de devis, rendez-vous, appels, e-mails) n'existe pas dans
le miroir. Seul le rythme de commande est mesurable.
"""
from __future__ import annotations

from datetime import date, datetime

# ── Pics d'activité ─────────────────────────────────────────────────────────
# Un mois pèse au moins 2,5 × la médiane mensuelle du compte pour être un pic.
# Même esprit que la rupture de rythme du briefing DG (silence > 2,5 × l'intervalle
# médian) : le facteur est le même pour que « pic » et « rupture » soient deux
# lectures symétriques d'un seul et même rythme.
FACTEUR_PIC = 2.5
# Plancher de montant : sans lui, un compte dont la médiane est à 800 000 FCFA
# déclenche une alerte à 2 M — un bruit qui noierait les vrais signaux (crainte
# explicite du DC : « combien d'alertes par semaine avant que cela devienne du
# bruit que l'on ignore »).
MONTANT_PLANCHER_PIC_XOF = 5_000_000
# Sous 3 commandes, une « médiane » n'a pas de sens statistique : le compte est
# déclaré non éligible plutôt que jugé sur deux points.
MIN_COMMANDES_POUR_PIC = 3
# Fenêtre d'observation, en mois glissants. Le CR demande une détection
# réactive ; au-delà de 3 mois, l'alerte arrive après la fenêtre de tir.
FENETRE_PIC_MOIS = 3


def _median(valeurs: list[float]) -> float:
    if not valeurs:
        return 0.0
    ordonnes = sorted(valeurs)
    milieu = len(ordonnes) // 2
    if len(ordonnes) % 2:
        return float(ordonnes[milieu])
    return (ordonnes[milieu - 1] + ordonnes[milieu]) / 2


def _parse_date(valeur: str | None) -> date | None:
    if not valeur:
        return None
    try:
        return datetime.strptime(str(valeur)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _mois_glissants(today: date, n: int) -> list[str]:
    """Les `n` derniers mois calendaires, du plus ancien au plus récent, mois
    courant inclus."""
    mois: list[str] = []
    annee, m = today.year, today.month
    for _ in range(n):
        mois.append(f"{annee:04d}-{m:02d}")
        m -= 1
        if m == 0:
            annee, m = annee - 1, 12
    return list(reversed(mois))


def _rangs_normalises(valeurs: dict[str, float]) -> dict[str, float]:
    """Rang de chaque clé ramené sur 0-100 (100 = meilleur).

    Passer par le rang et non par la valeur relative est délibéré : sur ce
    portefeuille, le premier compte pèse 8 864 M FCFA et le dixième 900 M. Une
    normalisation min-max écraserait tous les autres à quelques points et
    l'indice ne distinguerait plus rien au-delà du top 3.
    """
    if not valeurs:
        return {}
    ordonne = sorted(valeurs.items(), key=lambda kv: kv[1], reverse=True)
    n = len(ordonne)
    if n == 1:
        return {ordonne[0][0]: 100.0}
    return {cle: round(100 * (n - 1 - i) / (n - 1), 1) for i, (cle, _) in enumerate(ordonne)}


def build_top_comptes(
    comptes: list[dict],
    opportunites: list[dict],
    today: date | None = None,
    limit: int = 15,
) -> dict:
    """Classement des comptes sur les quatre mesures, en quantité ET en montant.

    `comptes` : sortie de `CRMRepository.get_account_activity()`.
    `opportunites` : sortie de `queries.fetch_opportunites()`.

    Les opportunités « à venir » sont les opportunités OUVERTES dont l'échéance
    n'est pas dépassée. Celles dont l'échéance est passée sont comptées à part
    (`nb_opp_echues`) et non dans le « à venir » : les mêmes affaires servaient
    déjà de forecast à un trimestre révolu, les compter comme du futur gonflerait
    le classement des comptes les moins bien tenus.
    """
    jour = today or date.today()

    # Opportunités ouvertes ventilées par compte. Le rapprochement se fait sur
    # `client_id` quand il existe et sur le NOM sinon : 83 opportunités portent un
    # `client_id` vide mais un nom exploitable, et ce sont des affaires réelles.
    par_id: dict[str, dict] = {}
    par_nom: dict[str, dict] = {}

    def _bucket(opp: dict) -> dict:
        cid = (opp.get("client_id") or "").strip()
        if cid:
            return par_id.setdefault(cid, {"a_venir_nb": 0, "a_venir_xof": 0, "echu_nb": 0, "echu_xof": 0})
        nom = (opp.get("client") or "").strip().upper()
        return par_nom.setdefault(nom, {"a_venir_nb": 0, "a_venir_xof": 0, "echu_nb": 0, "echu_xof": 0})

    for opp in opportunites:
        if not est_ouverte(opp["stage"]):
            continue
        b = _bucket(opp)
        echeance = _parse_date(opp.get("deadline"))
        if echeance is not None and echeance < jour:
            b["echu_nb"] += 1
            b["echu_xof"] += opp["montant_xof"]
        else:
            b["a_venir_nb"] += 1
            b["a_venir_xof"] += opp["montant_xof"]

    lignes: list[dict] = []
    for c in comptes:
        cid = (c.get("client_id") or "").strip()
        pipe = par_id.get(cid) or par_nom.get((c.get("compte") or "").strip().upper()) or {}
        ca = c.get("ca_total_xof", 0)
        nb_cmd = c.get("nb_commandes", 0)
        a_venir_nb = pipe.get("a_venir_nb", 0)
        a_venir_xof = pipe.get("a_venir_xof", 0)
        if ca <= 0 and a_venir_nb == 0:
            continue
        lignes.append({
            "compte": c.get("compte") or "(compte sans nom)",
            "client_id": cid or None,
            "commercial": c.get("commercial") or "",
            "ca_realise_xof": ca,
            "nb_commandes": nb_cmd,
            "panier_moyen_xof": round(ca / nb_cmd) if nb_cmd else 0,
            "nb_opp_a_venir": a_venir_nb,
            "pipe_a_venir_xof": a_venir_xof,
            "nb_opp_echues": pipe.get("echu_nb", 0),
            "pipe_echu_xof": pipe.get("echu_xof", 0),
            "derniere_commande": c.get("derniere_commande"),
            "alerte_impaye": bool(c.get("impaye_xof", 0) > 0),
        })

    rang_ca = _rangs_normalises({str(i): l["ca_realise_xof"] for i, l in enumerate(lignes)})
    rang_nb_cmd = _rangs_normalises({str(i): float(l["nb_commandes"]) for i, l in enumerate(lignes)})
    rang_pipe = _rangs_normalises({str(i): l["pipe_a_venir_xof"] for i, l in enumerate(lignes)})
    rang_nb_opp = _rangs_normalises({str(i): float(l["nb_opp_a_venir"]) for i, l in enumerate(lignes)})

    for i, l in enumerate(lignes):
        k = str(i)
        montant = (rang_ca.get(k, 0) + rang_pipe.get(k, 0)) / 2
        quantite = (rang_nb_cmd.get(k, 0) + rang_nb_opp.get(k, 0)) / 2
        l["indice_montant"] = round(montant, 1)
        l["indice_quantite"] = round(quantite, 1)
        l["indice_combine"] = round((montant + quantite) / 2, 1)
        # Au-delà de 25 points d'écart entre les deux lectures, le compte se juge
        # différemment selon la dimension regardée : c'est exactement le cas que
        # le DC veut voir signalé.
        l["ecart_lecture"] = round(montant - quantite, 1)
        l["lecture_divergente"] = abs(montant - quantite) >= 25

    lignes.sort(key=lambda l: l["indice_combine"], reverse=True)
    total_ca = sum(l["ca_realise_xof"] for l in lignes)
    total_pipe = sum(l["pipe_a_venir_xof"] for l in lignes)
    top = lignes[:limit]

    return {
        "as_of": jour.isoformat(),
        "comptes": top,
        "totaux": {
            "nb_comptes_classes": len(lignes),
            "ca_realise_xof": total_ca,
            "pipe_a_venir_xof": total_pipe,
            "part_ca_top_pct": round(100 * sum(l["ca_realise_xof"] for l in top) / total_ca, 1) if total_ca else 0.0,
            "part_pipe_top_pct": round(100 * sum(l["pipe_a_venir_xof"] for l in top) / total_pipe, 1) if total_pipe else 0.0,
            "nb_lectures_divergentes": sum(1 for l in lignes if l["lecture_divergente"]),
        },
        "note": (
            "Indice combiné calculé sur les RANGS des quatre mesures (CA réalisé et nombre de commandes "
            "pour le réalisé, pipe à venir et nombre d'opportunités pour le futur), jamais sur une somme : "
            "additionner des francs et des unités n'a pas de sens. Les comptes marqués « lecture divergente » "
            "changent de place selon qu'on les juge en quantité ou en montant."
        ),
    }


def est_ouverte(stage: str | None) -> bool:
    """Étape non close, détectée par MOTIF (16 libellés Odoo pour ~9 étapes)."""
    s = (stage or "").lower()
    return not any(p in s for p in ("gagn", "won", "perdu", "lost", "annul", "cancel"))


def build_pics_activite(series: list[dict], today: date | None = None, limit: int = 12) -> dict:
    """Comptes dont le rythme de commande s'emballe sur la fenêtre récente.

    `series` : sortie de `queries.fetch_series_mensuelles_par_compte()`.

    La médiane de référence exclut la fenêtre observée : sinon un pic élève sa
    propre référence et se masque lui-même.
    """
    jour = today or date.today()
    fenetre = set(_mois_glissants(jour, FENETRE_PIC_MOIS))
    mois_courant = f"{jour.year:04d}-{jour.month:02d}"

    par_compte: dict[str, dict] = {}
    for ligne in series:
        cid = ligne["client_id"]
        c = par_compte.setdefault(cid, {
            "compte": ligne["compte"], "client_id": cid, "commercial": ligne["commercial"], "mois": {},
        })
        c["mois"][ligne["mois"]] = {"nb": ligne["nb"], "montant_xof": ligne["montant_xof"]}

    pics: list[dict] = []
    nb_eligibles = 0
    for cid, c in par_compte.items():
        mois = c["mois"]
        nb_commandes = sum(m["nb"] for m in mois.values())
        historique = [m["montant_xof"] for cle, m in mois.items() if cle not in fenetre]
        if nb_commandes < MIN_COMMANDES_POUR_PIC or len(historique) < MIN_COMMANDES_POUR_PIC:
            continue
        nb_eligibles += 1
        mediane = _median(historique)
        if mediane <= 0:
            continue
        seuil = max(mediane * FACTEUR_PIC, MONTANT_PLANCHER_PIC_XOF)
        for cle in sorted(fenetre):
            observe = mois.get(cle)
            if not observe or observe["montant_xof"] < seuil:
                continue
            pics.append({
                "compte": c["compte"],
                "client_id": cid,
                "commercial": c["commercial"],
                "mois": cle,
                "mois_en_cours": cle == mois_courant,
                "montant_xof": observe["montant_xof"],
                "nb_commandes_mois": observe["nb"],
                "mediane_mensuelle_xof": round(mediane),
                "intensite": round(observe["montant_xof"] / mediane, 1),
                "nb_mois_historique": len(historique),
            })

    pics.sort(key=lambda p: (p["mois"], p["intensite"]), reverse=True)
    return {
        "as_of": jour.isoformat(),
        "fenetre_mois": sorted(fenetre),
        "seuils": {
            "facteur": FACTEUR_PIC,
            "montant_plancher_xof": MONTANT_PLANCHER_PIC_XOF,
            "min_commandes": MIN_COMMANDES_POUR_PIC,
        },
        "pics": pics[:limit],
        "couverture": {
            "nb_comptes_avec_commande": len(par_compte),
            "nb_comptes_eligibles": nb_eligibles,
            "nb_pics": len(pics),
            "part_eligible_pct": round(100 * nb_eligibles / len(par_compte), 1) if par_compte else 0.0,
        },
        "note": (
            "Pic mesuré sur les commandes signées, comparé à la médiane mensuelle du compte lui-même. "
            "Le pic par SOLLICITATION (demandes de devis, rendez-vous, appels, e-mails) n'est pas "
            "mesurable : ces échanges ne sont pas remontés de l'ERP. Un compte de moins de trois "
            "commandes est déclaré non éligible plutôt que jugé sur deux points."
        ),
    }


def build_acquisition(comptes: list[dict], today: date | None = None) -> dict:
    """Nouveaux comptes par année d'entrée, et état du vivier de prospects.

    « Nouveau compte » = première commande SIGNÉE dans l'année (question 32 du
    cadrage : un compte jamais facturé, pas un dormant réactivé — la réactivation
    est un autre indicateur, porté par le suivi de dormance).
    """
    jour = today or date.today()
    par_annee: dict[int, dict] = {}
    prospects = 0
    for c in comptes:
        premiere = _parse_date(c.get("premiere_commande"))
        if premiere is None:
            if c.get("derniere_commande") is None:
                prospects += 1
            continue
        a = par_annee.setdefault(premiere.year, {"annee": premiere.year, "nb_comptes": 0, "ca_xof": 0, "comptes": []})
        a["nb_comptes"] += 1
        a["ca_xof"] += c.get("ca_total_xof", 0)
        a["comptes"].append({
            "compte": c.get("compte"),
            "premiere_commande": c.get("premiere_commande"),
            "ca_total_xof": c.get("ca_total_xof", 0),
            "nb_commandes": c.get("nb_commandes", 0),
            "commercial": c.get("commercial") or "",
        })

    annees = sorted(par_annee.values(), key=lambda a: a["annee"])
    for a in annees:
        a["comptes"] = sorted(a["comptes"], key=lambda x: x["ca_total_xof"], reverse=True)[:8]

    courante = par_annee.get(jour.year, {"nb_comptes": 0, "ca_xof": 0})
    precedente = par_annee.get(jour.year - 1, {"nb_comptes": 0, "ca_xof": 0})
    return {
        "as_of": jour.isoformat(),
        "annees": annees,
        "annee_courante": {
            "annee": jour.year,
            "nb_comptes": courante.get("nb_comptes", 0),
            "ca_xof": courante.get("ca_xof", 0),
            "nb_comptes_annee_precedente": precedente.get("nb_comptes", 0),
        },
        "vivier": {
            "nb_prospects": prospects,
            "nb_comptes_avec_commande": sum(a["nb_comptes"] for a in annees),
        },
        "note": (
            "Un compte est « nouveau » l'année de sa PREMIÈRE commande signée. À ne pas confondre avec "
            "un compte dormant réactivé, qui relève du suivi de dormance. L'année en cours est "
            "incomplète par construction : elle ne se compare à une année pleine qu'à date équivalente."
        ),
    }
