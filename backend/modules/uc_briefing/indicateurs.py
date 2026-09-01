"""Indicateurs historisés du briefing — le socle du « delta plutôt que l'état ».

Un briefing quotidien qui affiche « 1,2 Md » est un tableau de bord. Ce qui en
fait un briefing, c'est « 1,2 Md (+85 M vs hier) ». Cela suppose de connaître la
valeur d'hier, que le miroir Odoo ne porte pas : il n'a que l'état du jour.

CE QUI REND L'HISTORIQUE DISPONIBLE TOUT DE SUITE
─────────────────────────────────────────────────
La réponse évidente — « historiser chaque nuit, et attendre un mois » — n'est
vraie que pour la moitié des indicateurs. Les autres sont RECONSTITUABLES sur
tout l'historique dès aujourd'hui, parce que les faits qui les composent portent
leur propre date :

  - `sale_orders.date_order` dit quand la commande est entrée ;
  - `invoices.invoice_date` quand la facture a été émise ;
  - `invoices.payment_date` quand elle a été réglée.

Le CA commandé au 12 juin n'a donc pas besoin d'avoir été mesuré le 12 juin : il
se recalcule. C'est la distinction `nature` :

  flux  → cumul de faits datés. Reconstituable exactement, sur toute la période
          couverte par le miroir.
  stock → état à un instant (pipe ouvert, backlog). Rien ne dit ce qu'il valait
          mardi, SAUF s'il existe un snapshot d'objets ce jour-là
          (`pipeline_snapshots`, `backlog_snapshots`) ou une reconstitution
          documentée (les impayés, via les dates de règlement).

UNE SEULE REQUÊTE POUR HIER ET POUR AUJOURD'HUI
──────────────────────────────────────────────
Chaque indicateur porte `sql_historique`, valable à N'IMPORTE QUELLE date, et
n'ajoute `sql_jour` que si la source du jour diffère vraiment de la source
historique (le pipe se lit sur `opportunities` aujourd'hui, sur
`pipeline_snapshots` hier). Quand une seule requête suffit, elle sert aux deux.

Ce n'est pas une économie de code, c'est une condition de justesse : un delta
entre une valeur mesurée par une requête et une valeur reconstituée par une
autre mesure l'écart entre les deux requêtes autant que le mouvement réel. La
règle est donc : même fonction, mêmes données, seule la date change.

LES REMISES À ZÉRO
──────────────────
Un cumul « depuis le 1er janvier » retombe à zéro le 1er janvier. Comparer le
2 janvier au 31 décembre produirait une chute de tout l'exercice présentée comme
le mouvement d'une nuit. `remise_a_zero` interdit ces comparaisons : le delta
répond « indisponible », jamais un chiffre faux.

CE QUI N'EST PAS ICI, ET POURQUOI
─────────────────────────────────
  - Trésorerie : `account.payment` et `account.bank.statement.line` ne sont pas
    synchronisés. Les 825,9 M relevés à l'audit ne sont pas dans l'application.
  - Taux d'occupation, intercontrat : `account.analytic.line` n'est pas
    synchronisé, et l'entreprise ne vend pas de régie (cf. le mix constructeurs).
  - Objectifs : `commercial_objectives` est vide. Aucun taux de couverture n'est
    calculable, et en dériver un serait inventer le dénominateur.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select, text

from core.montants import fcfa
from db.database import AsyncSessionLocal
from db.models import IndicatorSnapshotModel

logger = logging.getLogger(__name__)


# Étapes qui ferment une opportunité — même liste que `facts._STADES_FERMES`,
# transcrite en SQL. Le libellé vient d'Odoo en texte libre et mélange trois
# nomenclatures (« 6-Gagné » / « Won » / « Gagné », « 7-Perdu » / « Lost ») : on
# reconnaît par mot-clé, jamais par égalité. `lower()` suffit — aucun des mots
# retenus ne porte d'accent sur les caractères testés.
_MOTS_FERMES = ("gagn", "won", "perdu", "lost", "annul", "cancel", "suspendu")
_PIPE_OUVERT = " AND ".join(f"lower(stage) NOT LIKE '%{mot}%'" for mot in _MOTS_FERMES)


@dataclass(frozen=True)
class Indicateur:
    """Une grandeur suivie dans le temps.

    `sql_historique` prend un paramètre `:d` et rend la valeur À CETTE DATE.
    `sql_jour` n'existe que si la source du jour n'est pas la source historique.
    `reserve` est une phrase que TOUTE puce citant cet indicateur doit porter :
    c'est là que vivent les réserves d'audit qui rendraient le chiffre trompeur
    s'il était publié nu (avoirs non déduits, encours fournisseur non rapproché).
    """
    cle: str
    libelle: str
    unite: str                       # xof | nb | pct | jours
    nature: str                      # flux | stock
    sql_historique: str | None       # None = non reconstituable, seul le jour J est mesurable
    sql_jour: str | None = None      # None = `sql_historique` sert aussi pour aujourd'hui
    remise_a_zero: str | None = None  # annuelle | mensuelle | None
    reserve: str = ""
    # Table de snapshot d'OBJETS dont dépend la reconstitution. Une date sans
    # snapshot n'est pas une date à zéro : `calculer` rend None. Sans ce garde-fou,
    # un backlog jamais capturé le 12 juin se lirait comme un backlog tombé à zéro
    # ce jour-là — et le delta du lendemain afficherait une remontée de 9 Md.
    source_snapshot: str | None = None

    def requete(self, historique: bool) -> str | None:
        if historique:
            return self.sql_historique
        return self.sql_jour or self.sql_historique


# ── Flux : cumuls de faits datés, reconstituables sur tout l'historique ───────

# `SUM(amount)` et non `amount_untaxed` : ce dernier vaut 0 sur les 3 108
# commandes du miroir (Odoo ne le remonte pas). Le montant est donc TTC. C'est
# aussi ce que fait `get_ytd_stats`, et deux définitions du CA commandé sur le
# même écran seraient pires qu'une définition imparfaite documentée.
_CA_COMMANDE = """
    SELECT COALESCE(SUM(amount), 0) FROM sale_orders
    WHERE state IN ('sale', 'done') AND date_order IS NOT NULL
      AND date(date_order) <= date(:d) AND {periode}
"""
_NB_COMMANDES = """
    SELECT COUNT(*) FROM sale_orders
    WHERE state IN ('sale', 'done') AND date_order IS NOT NULL
      AND date(date_order) <= date(:d) AND {periode}
"""
_CA_FACTURE = """
    SELECT COALESCE(SUM(amount), 0) FROM invoices
    WHERE status != 'cancelled' AND invoice_date IS NOT NULL
      AND date(invoice_date) <= date(:d) AND {periode}
"""
# Une facture porte `payment_date` quand elle a été soldée : le cumul encaissé à
# la date D est la somme des factures soldées au plus tard ce jour-là. Les
# règlements partiels ne sont pas datés dans le miroir — ils basculent d'un coup
# le jour du solde. L'encaissement quotidien est donc juste en cumul et
# grossier au jour le jour ; la réserve le dit.
_ENCAISSEMENTS = """
    SELECT COALESCE(SUM(amount), 0) FROM invoices
    WHERE status != 'cancelled' AND payment_date IS NOT NULL
      AND date(payment_date) <= date(:d) AND {periode}
"""
_ACHATS = """
    SELECT COALESCE(SUM(amount), 0) FROM purchase_orders
    WHERE state = 'purchase' AND date_order IS NOT NULL
      AND date(date_order) <= date(:d) AND {periode}
"""

_ANNEE = "strftime('%Y', {col}) = strftime('%Y', :d)"
_MOIS = "strftime('%Y-%m', {col}) = strftime('%Y-%m', :d)"

# ── Stock : état à un instant ────────────────────────────────────────────────

_PIPE_JOUR = f"""
    SELECT COALESCE(SUM({{expr}}), 0) FROM opportunities
    WHERE {_PIPE_OUVERT} {{echeance}}
"""
_PIPE_HIST = f"""
    SELECT COALESCE(SUM({{expr}}), 0) FROM pipeline_snapshots
    WHERE snapshot_date = date(:d) AND {_PIPE_OUVERT} {{echeance}}
"""

# Un stade ouvert ne suffit pas à faire une affaire vivante. Sur les 3 348
# opportunités que le miroir déclare ouvertes, 3 015 — 82 % du montant, 107 881
# M FCFA — portent une date de clôture DÉJÀ PASSÉE : c'est l'anomalie A4
# (« opportunités périmées jamais clôturées, pipeline surévalué d'un facteur
# ~2 »), mesurée ici à un facteur 12 sur le montant.
#
# Publier « pipeline ouvert : 131 936 M FCFA » sans cette coupe donne au comité
# de direction un chiffre douze fois trop grand, avec l'autorité du calcul
# automatique. D'où trois indicateurs distincts plutôt qu'un : le total, la part
# encore dans les temps, et la part à assainir. Aucun ne remplace les deux
# autres — c'est leur écart qui est l'information.
_ECHEANCE_A_VENIR = "AND deadline IS NOT NULL AND date(deadline) >= date(:d)"
_ECHEANCE_PASSEE = "AND deadline IS NOT NULL AND date(deadline) < date(:d)"


def _pipe(cle, libelle, expr, unite, echeance="", reserve="") -> Indicateur:
    return Indicateur(
        cle=cle, libelle=libelle, unite=unite, nature="stock",
        sql_historique=_PIPE_HIST.format(expr=expr, echeance=echeance),
        sql_jour=_PIPE_JOUR.format(expr=expr, echeance=echeance),
        source_snapshot="pipeline_snapshots", reserve=reserve,
    )


_RESERVE_PIPE_BRUT = (
    "toutes échéances confondues, y compris les affaires dont la date de clôture "
    "est passée — comparer à `pipe_actif_brut` avant toute lecture"
)

# Reconstitution des impayés — hypothèse explicite : une facture réglée l'a été
# en une fois, à `payment_date`. Elle pesait donc son montant plein jusqu'à ce
# jour, et rien ensuite. Une facture encore ouverte pèse son reste dû actuel.
# C'est faux sur les règlements échelonnés, que le miroir ne date pas ; la
# réserve de l'indicateur le porte.
_IMPAYES = """
    SELECT COALESCE(SUM(CASE WHEN payment_date IS NULL THEN amount_residual ELSE amount END), 0)
    FROM invoices
    WHERE status != 'cancelled'
      AND invoice_date IS NOT NULL AND date(invoice_date) <= date(:d)
      AND due_date IS NOT NULL AND date(due_date) < date(:d, '{recul}')
      AND (payment_date IS NULL OR date(payment_date) > date(:d))
"""

_RESERVE_AVOIRS = (
    "les avoirs ne sont pas déduits — leur poids est passé de 1 % à 28 % du facturé "
    "brut entre 2019 et 2026"
)
_RESERVE_ECHEANCE = (
    "43 % des factures portent une échéance égale à leur date d'émission, ce qui "
    "sous-estime le retard réel sur cette part du portefeuille"
)
_RESERVE_FOURNISSEUR = (
    "encours non rapproché de la balance comptable (25 944 décaissements sans "
    "lettrage) — chiffre non publiable avant arbitrage de la Comptabilité"
)


def _flux(cle, libelle, gabarit, col, remise, unite="xof", reserve="") -> Indicateur:
    periode = (_ANNEE if remise == "annuelle" else _MOIS).format(col=col)
    return Indicateur(
        cle=cle, libelle=libelle, unite=unite, nature="flux",
        sql_historique=gabarit.format(periode=periode),
        remise_a_zero=remise, reserve=reserve,
    )


CATALOGUE: dict[str, Indicateur] = {ind.cle: ind for ind in [
    # ── Flux ──────────────────────────────────────────────────────────────────
    _flux("ca_commande_ytd", "CA commandé depuis le 1er janvier",
          _CA_COMMANDE, "date_order", "annuelle"),
    _flux("ca_commande_mois", "CA commandé sur le mois en cours",
          _CA_COMMANDE, "date_order", "mensuelle"),
    _flux("nb_commandes_ytd", "Commandes prises depuis le 1er janvier",
          _NB_COMMANDES, "date_order", "annuelle", unite="nb"),
    _flux("ca_facture_ytd", "CA facturé depuis le 1er janvier",
          _CA_FACTURE, "invoice_date", "annuelle", reserve=_RESERVE_AVOIRS),
    _flux("ca_facture_mois", "CA facturé sur le mois en cours",
          _CA_FACTURE, "invoice_date", "mensuelle", reserve=_RESERVE_AVOIRS),
    _flux("encaissements_ytd", "Encaissements depuis le 1er janvier",
          _ENCAISSEMENTS, "payment_date", "annuelle",
          reserve="une facture bascule d'un coup le jour de son solde, les règlements "
                  "partiels n'étant pas datés dans le miroir"),
    _flux("encaissements_mois", "Encaissements sur le mois en cours",
          _ENCAISSEMENTS, "payment_date", "mensuelle",
          reserve="une facture bascule d'un coup le jour de son solde, les règlements "
                  "partiels n'étant pas datés dans le miroir"),
    _flux("achats_engages_ytd", "Achats engagés depuis le 1er janvier",
          _ACHATS, "date_order", "annuelle"),

    # ── Stock reconstituable depuis les snapshots d'objets ────────────────────
    _pipe("pipe_brut", "Pipeline ouvert, toutes échéances (brut)",
          "expected_revenue", "xof", reserve=_RESERVE_PIPE_BRUT),
    _pipe("pipe_pondere", "Pipeline ouvert, toutes échéances (pondéré)",
          "expected_revenue * probability / 100.0", "xof", reserve=_RESERVE_PIPE_BRUT),
    _pipe("nb_opportunites_ouvertes", "Opportunités ouvertes, toutes échéances",
          "1", "nb", reserve=_RESERVE_PIPE_BRUT),
    _pipe("pipe_actif_brut", "Pipeline encore dans les temps (brut)",
          "expected_revenue", "xof", _ECHEANCE_A_VENIR),
    _pipe("pipe_actif_pondere", "Pipeline encore dans les temps (pondéré)",
          "expected_revenue * probability / 100.0", "xof", _ECHEANCE_A_VENIR),
    _pipe("nb_opportunites_actives", "Opportunités dont l'échéance est à venir",
          "1", "nb", _ECHEANCE_A_VENIR),
    _pipe("pipe_echu", "Pipeline à échéance dépassée (à assainir)",
          "expected_revenue", "xof", _ECHEANCE_PASSEE),
    _pipe("nb_opportunites_echues", "Opportunités à échéance dépassée",
          "1", "nb", _ECHEANCE_PASSEE),
    Indicateur(
        "backlog", "Backlog non facturé", "xof", "stock",
        sql_historique="SELECT COALESCE(SUM(backlog), 0) FROM backlog_snapshots "
                       "WHERE snapshot_date = date(:d)",
        sql_jour="SELECT COALESCE(SUM(backlog), 0) FROM dossiers",
            source_snapshot="backlog_snapshots",
    ),
    Indicateur(
        "reste_a_encaisser", "Reste à encaisser sur dossiers", "xof", "stock",
        sql_historique="SELECT COALESCE(SUM(reste_a_encaisser), 0) FROM backlog_snapshots "
                       "WHERE snapshot_date = date(:d)",
        sql_jour="SELECT COALESCE(SUM(reste_a_encaisser), 0) FROM dossiers",
            source_snapshot="backlog_snapshots",
    ),

    # ── Stock reconstituable depuis les dates de règlement ────────────────────
    Indicateur(
        "impayes_echus", "Impayés clients échus", "xof", "stock",
        sql_historique=_IMPAYES.format(recul="+0 day"), reserve=_RESERVE_ECHEANCE,
    ),
    Indicateur(
        "impayes_echus_90j", "Impayés clients échus depuis plus de 90 jours", "xof", "stock",
        sql_historique=_IMPAYES.format(recul="-90 day"), reserve=_RESERVE_ECHEANCE,
    ),
    Indicateur(
        "dette_fournisseurs_echue", "Dette fournisseurs échue", "xof", "stock",
        sql_historique=_IMPAYES.replace("invoices", "supplier_invoices")
                               .replace("status != 'cancelled'", "payment_state != 'cancel'")
                               .format(recul="+0 day"),
        reserve=_RESERVE_FOURNISSEUR,
    ),
]}


# ── Calcul ────────────────────────────────────────────────────────────────────

async def calculer(cle: str, jour: date, *, historique: bool | None = None) -> float | None:
    """Valeur d'un indicateur à une date. `None` quand elle n'est pas mesurable
    — un stock sans snapshot ce jour-là, jamais un zéro.

    Le contrôle de snapshot est ici, et non chez l'appelant : la requête
    historique d'un stock est un `SUM ... WHERE snapshot_date = :d`, qui rend
    tranquillement 0 quand la journée n'a jamais été capturée. Ce zéro est le
    piège central de tout ce module — il se lit comme un backlog effondré, et le
    delta du lendemain comme une remontée de neuf milliards. Un seul garde-fou,
    au seul endroit par lequel toutes les lectures passent.
    """
    ind = CATALOGUE.get(cle)
    if ind is None:
        raise KeyError(f"Indicateur inconnu : {cle}")
    if historique is None:
        historique = jour != date.today()
    requete = ind.requete(historique)
    if requete is None:
        return None
    if historique and ind.source_snapshot and jour not in await _jours_snapshotes(ind.source_snapshot):
        return None
    async with AsyncSessionLocal() as session:
        valeur = (await session.execute(text(requete), {"d": jour.isoformat()})).scalar()
    return None if valeur is None else float(valeur)


# Mémoïsation des dates de snapshot : `calculer` interroge cette table à chaque
# indicateur ET chaque jour reconstitué — un backfill d'un an ferait sinon
# 5 × 365 SELECT DISTINCT sur une donnée qui ne bouge qu'une fois par nuit.
# `vider_cache_snapshots` est appelé par le job après écriture.
_CACHE_JOURS: dict[str, set[date]] = {}


def vider_cache_snapshots() -> None:
    _CACHE_JOURS.clear()


async def _jours_snapshotes(table: str) -> set[date]:
    """Dates où un snapshot d'objets existe — les seules où un stock est
    reconstituable."""
    connu = _CACHE_JOURS.get(table)
    if connu is not None:
        return connu
    async with AsyncSessionLocal() as session:
        lignes = (await session.execute(text(f"SELECT DISTINCT snapshot_date FROM {table}"))).all()
    jours = set()
    for (brut,) in lignes:
        if isinstance(brut, date):
            jours.add(brut)
        elif brut:
            jours.add(date.fromisoformat(str(brut)[:10]))
    _CACHE_JOURS[table] = jours
    return jours


async def enregistrer(jour: date, valeurs: dict[str, float], origine: str) -> int:
    """Écrit les valeurs du jour. Idempotent : un rerun remplace la journée
    plutôt que de la dupliquer (même contrat que `run_pipeline_snapshot`)."""
    if not valeurs:
        return 0
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(IndicatorSnapshotModel).where(
                IndicatorSnapshotModel.snapshot_date == jour,
                IndicatorSnapshotModel.cle.in_(list(valeurs)),
            )
        )
        maintenant = datetime.utcnow()
        for cle, valeur in valeurs.items():
            ind = CATALOGUE[cle]
            session.add(IndicatorSnapshotModel(
                snapshot_date=jour, cle=cle, valeur=float(valeur),
                unite=ind.unite, nature=ind.nature, origine=origine, calcule_le=maintenant,
            ))
        await session.commit()
    return len(valeurs)


async def capturer_jour(jour: date | None = None) -> dict[str, float]:
    """Mesure tous les indicateurs sur l'état du jour et les enregistre."""
    jour = jour or date.today()
    valeurs: dict[str, float] = {}
    for cle in CATALOGUE:
        valeur = await calculer(cle, jour, historique=False)
        if valeur is not None:
            valeurs[cle] = valeur
    await enregistrer(jour, valeurs, origine="mesure")
    return valeurs


async def reconstituer(depuis: date, jusqu_a: date | None = None) -> dict[str, int]:
    """Reconstitue l'historique sur la fenêtre demandée.

    C'est ce qui rend le delta disponible dès le premier jour au lieu du
    trentième : les flux se recalculent intégralement depuis les dates portées
    par les faits, les impayés depuis les dates de règlement, et les stocks
    adossés à un snapshot d'objets aux seules dates où ce snapshot existe —
    `calculer` écarte les autres de lui-même.

    Ne touche jamais une journée déjà MESURÉE : une reconstitution approchée ne
    doit pas écraser une valeur relevée le jour dit. Une journée déjà
    reconstituée, en revanche, est recalculée — c'est ce qui permet de rejouer
    un backfill après correction d'une requête.
    """
    jusqu_a = jusqu_a or date.today()
    if depuis > jusqu_a:
        raise ValueError(f"Fenêtre vide : {depuis} > {jusqu_a}")
    vider_cache_snapshots()

    async with AsyncSessionLocal() as session:
        deja = {
            (ligne.snapshot_date, ligne.cle)
            for ligne in (await session.execute(
                select(IndicatorSnapshotModel).where(
                    IndicatorSnapshotModel.snapshot_date >= depuis,
                    IndicatorSnapshotModel.snapshot_date <= jusqu_a,
                    IndicatorSnapshotModel.origine == "mesure",
                )
            )).scalars()
        }

    compte = {"jours": 0, "valeurs": 0, "non_mesurables": 0}
    jour = depuis
    while jour <= jusqu_a:
        valeurs: dict[str, float] = {}
        for cle in CATALOGUE:
            if (jour, cle) in deja:
                continue
            valeur = await calculer(cle, jour, historique=True)
            if valeur is None:
                compte["non_mesurables"] += 1
            else:
                valeurs[cle] = valeur
        if valeurs:
            await enregistrer(jour, valeurs, origine="reconstitue")
            compte["valeurs"] += len(valeurs)
        compte["jours"] += 1
        jour += timedelta(days=1)
    logger.info(
        "Reconstitution des indicateurs du %s au %s : %d valeurs sur %d jours "
        "(%d non mesurables, faute de snapshot ce jour-là)",
        depuis, jusqu_a, compte["valeurs"], compte["jours"], compte["non_mesurables"],
    )
    return compte


# ── Lecture : le delta ────────────────────────────────────────────────────────

# Horizon nominal, et jusqu'où on accepte de reculer pour trouver un point de
# comparaison. La tolérance n'existe que pour les STOCKS : les flux sont
# reconstitués jour par jour, leur date exacte est toujours là. Un stock, lui,
# ne connaît que les jours où un snapshot d'objets a été pris — et ces jours
# sont rares tant que le job de nuit n'a pas tourné un mois.
#
# Reculer sans le dire transformerait « vs hier » en « vs il y a trois
# semaines » sans que le lecteur le sache : c'est pourquoi chaque horizon rend
# AUSSI la date réellement comparée, et `formater` l'affiche dès qu'elle
# s'écarte de l'horizon demandé.
_HORIZONS = {"j1": (1, 3), "semaine": (7, 7), "mois": (30, 20)}

# Comment chaque horizon se dit. Table séparée de `_HORIZONS` mais tenue en
# regard : le suffixe de puce et la ligne de cadence les lisent tous les deux,
# et un horizon ajouté sans son libellé lèverait un KeyError à la rédaction
# plutôt qu'au chargement.
_LIBELLES_HORIZON = {"j1": "vs hier", "semaine": "sur 7 j", "mois": "sur 30 j"}


def _comparable(ind: Indicateur, reference: date, compare: date) -> bool:
    """Un cumul « depuis le 1er janvier » retombe à zéro le 1er janvier :
    comparer le 2 janvier au 31 décembre présenterait la remise à zéro de
    l'exercice comme le mouvement d'une nuit."""
    if ind.remise_a_zero == "annuelle":
        return reference.year == compare.year
    if ind.remise_a_zero == "mensuelle":
        return (reference.year, reference.month) == (compare.year, compare.month)
    return True


def _point_de_comparaison(
    ind: Indicateur, connues: dict[date, float], as_of: date, cible: date, tolerance: int
) -> tuple[date, float] | None:
    """Valeur connue la plus PROCHE de `cible`, dans la tolérance.

    La recherche s'écarte de la cible dans les deux sens, et non seulement vers
    le passé : un horizon « 30 jours » visant le 27/07 raterait sinon le
    snapshot du 28/07 pour un jour d'écart, alors qu'un point à 29 jours répond
    exactement à la question posée.

    Deux bornes ne sont jamais franchies : `as_of` lui-même (comparer une valeur
    à elle-même donnerait un mouvement nul trompeur) et une remise à zéro de
    période.
    """
    # L'ARRIÈRE D'ABORD, sur toute la tolérance, et l'avant seulement ensuite.
    # Une recherche symétrique rang par rang paraît plus naturelle mais choisit
    # mal : pour un horizon « 7 jours » visant le 20/08 avec des snapshots au
    # 13/08 et au 26/08, elle retient le 26/08 (à 6 rangs, mais à un seul jour
    # d'aujourd'hui) et présente une variation d'une nuit comme une variation
    # d'une semaine. Reculer d'abord garantit que le point retenu est au moins
    # aussi ancien que l'horizon demandé chaque fois qu'un tel point existe.
    for ecart in range(tolerance + 1):
        jour = cible - timedelta(days=ecart)
        valeur = connues.get(jour)
        if valeur is not None and jour < as_of and _comparable(ind, as_of, jour):
            return jour, valeur
    for ecart in range(1, tolerance + 1):
        jour = cible + timedelta(days=ecart)
        valeur = connues.get(jour)
        if valeur is not None and jour < as_of and _comparable(ind, as_of, jour):
            return jour, valeur
    return None


async def delta(cles: list[str], as_of: date | None = None) -> dict[str, dict]:
    """Valeur du jour et variations sur les trois horizons, par indicateur.

    Un horizon sans point de comparaison rend `None` et n'apparaît pas comme un
    zéro : « pas mesuré » et « n'a pas bougé » sont deux informations opposées,
    et les confondre est exactement ce qui fait publier un chiffre faux avec
    l'autorité de l'automatisation.

    Trois horizons et non un seul parce que le volume l'impose : l'entreprise
    prend environ deux commandes par jour ouvré et un jour ouvré sur trois n'en
    voit aucune (109 jours avec commande sur ~165 en 2026). Un delta strictement
    J-1 serait plat la plupart du temps.
    """
    as_of = as_of or date.today()
    voulues = [c for c in cles if c in CATALOGUE]
    if not voulues:
        return {}

    # Toutes les dates atteignables par un horizon ET sa tolérance : une seule
    # requête, plutôt qu'une par indicateur et par horizon.
    plus_ancien = min(
        as_of - timedelta(days=jours + tol) for jours, tol in _HORIZONS.values()
    )
    async with AsyncSessionLocal() as session:
        lignes = (await session.execute(
            select(IndicatorSnapshotModel).where(
                IndicatorSnapshotModel.cle.in_(voulues),
                IndicatorSnapshotModel.snapshot_date >= plus_ancien,
                IndicatorSnapshotModel.snapshot_date <= as_of,
            )
        )).scalars().all()
    par_cle: dict[str, dict[date, float]] = {}
    for ligne in lignes:
        par_cle.setdefault(ligne.cle, {})[ligne.snapshot_date] = ligne.valeur

    resultat: dict[str, dict] = {}
    for cle in voulues:
        ind = CATALOGUE[cle]
        connues = par_cle.get(cle, {})
        valeur = connues.get(as_of)
        if valeur is None:
            # Le job de nuit n'est pas passé (ou l'appel précède 1h15) : on
            # calcule à la volée plutôt que de rendre le briefing muet.
            valeur = await calculer(cle, as_of, historique=False)
        bloc: dict = {
            "cle": cle, "libelle": ind.libelle, "unite": ind.unite,
            "nature": ind.nature, "valeur": valeur, "reserve": ind.reserve,
        }
        for nom, (jours, tolerance) in _HORIZONS.items():
            point = (
                None if valeur is None
                else _point_de_comparaison(
                    ind, connues, as_of, as_of - timedelta(days=jours), tolerance
                )
            )
            if point is None:
                bloc[nom] = None
                bloc[f"{nom}_depuis"] = None
                bloc[f"{nom}_jours"] = None
            else:
                jour_compare, precedent = point
                bloc[nom] = valeur - precedent
                bloc[f"{nom}_depuis"] = jour_compare.isoformat()
                bloc[f"{nom}_jours"] = (as_of - jour_compare).days
        resultat[cle] = bloc
    return resultat


def _mouvement(bloc: dict, horizon: str) -> str:
    """Mouvement nu d'un horizon : « ▲ 85 M FCFA vs hier », « stable sur 7 j »,
    ou "" quand la comparaison n'est pas mesurable.

    Extrait de `formater` quand la ligne de cadence (cf. `ligne_cadence`) est
    venue dire le MÊME écart ailleurs dans le briefing. Deux rédactions du même
    mouvement finiraient par diverger — un arrondi ici, un symbole là — et le
    lecteur qui voit la puce et la ligne côte à côte lirait deux vérités pour un
    seul chiffre.
    """
    ecart = bloc.get(horizon)
    if ecart is None:
        return ""
    attendu = _HORIZONS[horizon][0]
    reels = bloc.get(f"{horizon}_jours")
    if reels is not None and reels != attendu:
        libelle = f"depuis le {_jj_mm(bloc.get(f'{horizon}_depuis'))}"
    else:
        libelle = _LIBELLES_HORIZON[horizon]

    if bloc.get("unite") == "nb":
        if not ecart:
            return f"stable {libelle}"
        return f"{'▲' if ecart > 0 else '▼'} {abs(int(ecart))} {libelle}"
    # Le seuil de « stabilité » reste le million : sous ce niveau, une variation
    # n'est pas un mouvement à signaler dans un briefing de direction. C'est une
    # règle de LECTURE, distincte de l'écriture du montant — qui passe par `fcfa`
    # et suit l'échelle propre à l'écart (85 M, 2,55 Md).
    if not round(abs(ecart) / 1_000_000):
        return f"stable {libelle}"
    return f"{'▲' if ecart > 0 else '▼'} {fcfa(abs(ecart))} FCFA {libelle}"


def formater(bloc: dict, horizon: str = "j1") -> str:
    """Suffixe de puce : « (▲ 85 M FCFA vs hier) », ou le silence.

    Rend "" quand la variation n'est pas mesurable — une puce sans delta reste
    une puce juste, une puce affichant « +0 » sur une comparaison impossible est
    un mensonge.

    Quand le point de comparaison n'est pas celui demandé (un stock dont le
    dernier snapshot date de treize jours), la puce le DATE au lieu de dire
    « vs hier ». Une comparaison silencieusement décalée est pire que pas de
    comparaison du tout : elle est invérifiable par le lecteur.
    """
    mouvement = _mouvement(bloc, horizon)
    return f" ({mouvement})" if mouvement else ""


def _valeur_lisible(bloc: dict) -> str:
    """Valeur du jour d'un indicateur, dans son unité."""
    valeur = bloc.get("valeur")
    unite = bloc.get("unite")
    if unite == "nb":
        return f"{int(valeur)}"
    if unite == "pct":
        return f"{valeur:.1f} %"
    if unite == "jours":
        return f"{round(valeur)} j"
    return f"{fcfa(valeur)} FCFA"


def ligne_cadence(bloc: dict | None, libelle: str) -> str:
    """Ligne de cadence d'un indicateur : sa valeur du jour, puis son mouvement
    sur chacun des trois horizons — « CA commandé : 6 128 M FCFA — stable vs
    hier, stable sur 7 j, ▲ 17 M FCFA sur 30 j. »

    C'est la même donnée que le suffixe de puce, mais lue autrement : la puce
    répond « où en est-on », la ligne répond « à quel rythme ça bouge ». Un
    directeur qui lit « 6 128 M » sans son rythme ne sait pas si le chiffre est
    acquis ou s'il court encore.

    LES HORIZONS ABSENTS SONT TUS, PAS COMBLÉS. Un stock historisé depuis cinq
    jours n'a pas de point à trente jours : la ligne dit alors ce qu'elle sait
    et se tait sur le reste. Aucun horizon mesurable — l'historisation n'a pas
    encore tourné deux nuits — et la ligne entière disparaît plutôt que
    d'annoncer un mouvement nul qui n'a pas été mesuré.
    """
    if not bloc or bloc.get("valeur") is None:
        return ""
    mouvements = [m for m in (_mouvement(bloc, h) for h in _HORIZONS) if m]
    if not mouvements:
        return ""
    return f"{libelle} : {_valeur_lisible(bloc)} — {', '.join(mouvements)}."


def _jj_mm(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}" if iso and len(iso) >= 10 else "?"


async def couverture() -> dict:
    """État de l'historisation — ce que le briefing peut promettre aujourd'hui.

    Sert l'écran de réglages et les tests de non-régression : sans cette vue,
    une rupture du job de nuit se manifeste par des deltas qui disparaissent
    silencieusement des puces, sans que personne sache pourquoi.
    """
    async with AsyncSessionLocal() as session:
        lignes = (await session.execute(text(
            "SELECT cle, COUNT(*), MIN(snapshot_date), MAX(snapshot_date), "
            "       SUM(CASE WHEN origine = 'mesure' THEN 1 ELSE 0 END) "
            "FROM indicator_snapshots GROUP BY cle"
        ))).all()
    par_cle = {
        cle: {"jours": n, "depuis": str(mini)[:10], "jusqu_a": str(maxi)[:10], "mesures": mes}
        for cle, n, mini, maxi, mes in lignes
    }
    return {
        "indicateurs": len(CATALOGUE),
        "historises": len(par_cle),
        "detail": {cle: par_cle.get(cle) for cle in CATALOGUE},
    }
