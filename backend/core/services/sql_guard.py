"""
Garde-fou text-to-SQL partagé (Phase 3).

Valide une requête SQL générée par LLM AVANT exécution. Conçu pour SQLite et
durci contre les contournements (multi-statements, commentaires, ATTACH/PRAGMA,
fonctions dangereuses, accès hors liste blanche, sqlite_master). Fail-closed :
toute violation lève SqlGuardError ; rien n'est exécuté.

NB : la défense en profondeur est complétée côté connexion par `mode=ro` +
`PRAGMA query_only=ON` (cf. adapters/kb/readonly_sql_adapter.py). Ce module est
la barrière applicative ; il ne remplace pas la connexion en lecture seule.
"""
from __future__ import annotations

import re

# Mots-clés d'écriture / DDL / dangereux (refus par \bMOT\b, insensible à la casse).
_FORBIDDEN = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "RENAME", "REPLACE", "MERGE", "GRANT", "REVOKE", "UPSERT",
    "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX", "ANALYZE",
    # Fonctions SQLite dangereuses (RCE / exfiltration)
    "LOAD_EXTENSION", "READFILE", "WRITEFILE", "EDIT", "FTS3_TOKENIZER",
    # Pseudo-tables système
    "SQLITE_MASTER", "SQLITE_SCHEMA", "SQLITE_TEMP_MASTER",
]
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(_FORBIDDEN) + r")\b", re.IGNORECASE)

# Identifiants de tables après FROM/JOIN. On capture aussi le caractère suivant
# pour distinguer une table d'une fonction table-valued (ex. json_each(...)).
_TABLE_RE = re.compile(r'\b(?:FROM|JOIN)\s+["`\[]?([a-zA-Z_][a-zA-Z0-9_]*)["`\]]?\s*(\(?)', re.IGNORECASE)

_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)", re.IGNORECASE)

# Fonctions table-valued autorisées (ne sont pas des tables à filtrer).
_TABLE_FUNCS = {"json_each", "json_tree"}


class SqlGuardError(Exception):
    """Requête SQL rejetée par le garde-fou."""


def validate_select(
    sql: str,
    allowed_tables: set[str],
    *,
    max_limit: int = 200,
    max_joins: int = 8,
    max_len: int = 4000,
) -> str:
    """
    Valide une requête en lecture seule bornée à `allowed_tables` et renvoie la
    requête assainie (LIMIT clampé). Lève SqlGuardError sinon.
    """
    if not sql or not sql.strip():
        raise SqlGuardError("Requête SQL vide.")

    cleaned = sql.strip().rstrip(";").strip()

    if len(cleaned) > max_len:
        raise SqlGuardError(f"Requête trop longue (> {max_len} caractères).")

    # Commentaires interdits (vecteur de masquage / contournement de regex).
    if "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
        raise SqlGuardError("Les commentaires SQL (-- ou /* */) sont interdits.")

    # Statement unique.
    if ";" in cleaned:
        raise SqlGuardError("Une seule requête à la fois (point-virgule interne interdit).")

    upper = cleaned.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise SqlGuardError("Seules les requêtes SELECT (ou WITH … SELECT) sont autorisées.")

    forbidden = _FORBIDDEN_RE.search(cleaned)
    if forbidden:
        raise SqlGuardError(f"Mot-clé interdit : '{forbidden.group(1).upper()}'. Lecture seule uniquement.")

    if upper.count(" JOIN ") > max_joins:
        raise SqlGuardError(f"Trop de jointures (> {max_joins}).")

    # Liste blanche de tables (deny-by-default).
    allowed_lower = {t.lower() for t in allowed_tables}
    for name, paren in _TABLE_RE.findall(cleaned):
        ident = name.lower()
        if paren == "(" or ident in _TABLE_FUNCS:
            continue  # fonction table-valued (json_each…), pas une table
        if ident not in allowed_lower:
            raise SqlGuardError(
                f"Table non autorisée : '{name}'. Tables permises : {', '.join(sorted(allowed_lower))}."
            )

    # LIMIT borné : clamp des valeurs > max, injection si absent.
    if _LIMIT_RE.search(cleaned):
        def _clamp(m):
            n = int(m.group(1))
            return f"LIMIT {min(n, max_limit)}"
        cleaned = _LIMIT_RE.sub(_clamp, cleaned)
    else:
        cleaned = f"{cleaned} LIMIT {max_limit}"

    return cleaned
