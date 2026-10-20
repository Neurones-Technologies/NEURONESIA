"""Périmètre pays d'une requête — appliqué en UN point, à toutes les lectures.

Le pays d'un compte (users.pays) est un périmètre IMPOSÉ : toutes ses pages ne
doivent montrer que les données de son entité. Le poser requête par requête
dans des centaines de lectures serait fragile — une seule oubliée suffit à
montrer des chiffres CI à un compte BF. Il est donc appliqué à la connexion :

1. `definir()` pose l'entité de la requête HTTP en cours (contextvar, propre à
   la tâche asyncio : deux requêtes simultanées de deux pays ne se mélangent
   pas). Posé par l'authentification (api/v1/dependencies.py).
2. Un hook SQLAlchemy (`installer`) réécrit tout SELECT qui lit une vue portant
   `entite` en sa version restreinte :
       FROM v_creances c   →   FROM (SELECT * FROM v_creances WHERE entite = 'BF') c
   SQL écrit à la main, requêtes ORM et assistant SQL passent tous par là.

Hors requête (jobs planifiés, tests), aucune entité n'est posée : rien n'est
réécrit. Ce qui n'a pas d'entité (fiches clients, factures fournisseurs, tables
brutes Odoo) n'est pas filtrable ici : les écrans le présentent comme
« chiffres groupe ».
"""
from __future__ import annotations

import re
from contextvars import ContextVar

from core.services.entites import ENTITES

_ENTITE: ContextVar[str | None] = ContextVar("perimetre_entite", default=None)

# Vues portant `entite` (cf. db/views.py). Les pivots (v_entite_*) n'y sont pas :
# ils servent aux définitions de vues, jamais aux écrans.
VUES_FILTRABLES = frozenset({
    "v_commandes", "v_sale_orders", "v_lignes_commande", "v_factures", "v_purchase_orders",
    "v_opportunities", "v_creances", "v_dossiers", "v_jalons", "v_demandes_facturation",
    "v_fiches", "v_consultations", "v_sale_orders_odoo", "v_achats_odoo",
})

# Mots qui peuvent suivre un nom de table sans en être l'alias.
_MOTS_SQL = frozenset({
    "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS", "FULL", "NATURAL", "ON",
    "USING", "GROUP", "ORDER", "LIMIT", "OFFSET", "UNION", "EXCEPT", "INTERSECT", "HAVING",
    "WINDOW", "AS",
})

# FROM / JOIN / virgule (jointure implicite), puis un nom de vue NON suivi d'un
# point (référence de colonne `v_x.col`) ni d'une parenthèse, puis alias éventuel.
_RE_VUE = re.compile(
    r"(?P<avant>\bFROM|\bJOIN|,)(?P<esp>\s+)(?P<vue>"
    + "|".join(sorted(VUES_FILTRABLES, key=len, reverse=True))
    + r")\b(?![.(])(?P<suite>\s+(?:AS\s+)?(?P<alias>[A-Za-z_][A-Za-z0-9_]*))?",
    re.IGNORECASE,
)


def entite_courante() -> str | None:
    """Entité imposée à la requête en cours (CI / BF / GN), ou None = groupe."""
    return _ENTITE.get()


def definir(entite: str | None):
    """Pose l'entité de la requête en cours. Toute valeur hors liste blanche est
    refusée : elle finit dans du SQL."""
    if entite is not None and entite not in ENTITES:
        raise ValueError(f"Entité inconnue : {entite!r}")
    return _ENTITE.set(entite)


def reinitialiser(jeton) -> None:
    _ENTITE.reset(jeton)


def reecrire(sql: str, entite: str) -> str:
    """Restreint chaque lecture d'une vue filtrable à `entite`."""
    if entite not in ENTITES:
        raise ValueError(f"Entité inconnue : {entite!r}")

    def remplacer(m: re.Match) -> str:
        vue = m.group("vue").lower()
        sous_requete = f"(SELECT * FROM {vue} WHERE entite = '{entite}')"
        suite, alias = m.group("suite") or "", m.group("alias")
        if alias and alias.upper() not in _MOTS_SQL:
            return f"{m.group('avant')}{m.group('esp')}{sous_requete}{suite}"
        # Sans alias, la sous-requête reprend le nom de la vue : les références
        # `v_x.colonne` du reste de la requête (ORM) restent valides.
        return f"{m.group('avant')}{m.group('esp')}{sous_requete} AS {vue}{suite}"

    return _RE_VUE.sub(remplacer, sql)


def _est_lecture(sql: str) -> bool:
    debut = sql.lstrip()[:10].upper()
    return debut.startswith("SELECT") or debut.startswith("WITH")


def _avant_execution(conn, cursor, statement, parameters, context, executemany):
    entite = _ENTITE.get()
    if entite and _est_lecture(statement):
        statement = reecrire(statement, entite)
    return statement, parameters


def installer(sync_engine) -> None:
    """Branche la réécriture sur un moteur (synchrone sous-jacent d'un AsyncEngine)."""
    from sqlalchemy import event
    if not event.contains(sync_engine, "before_cursor_execute", _avant_execution):
        event.listen(sync_engine, "before_cursor_execute", _avant_execution, retval=True)
