"""
ReadOnlySqlAdapter — exécution de SELECT générés par LLM en LECTURE SEULE.

Double barrière (cf. red-team Phase 3) :
- Connexion ouverte avec `mode=ro` (O_RDONLY au niveau OS) ;
- `PRAGMA query_only=ON` (rejet de tout DML au parser SQLite).
Indépendant du moteur read-write existant (db/database.py). La validation
applicative (liste blanche, SELECT-only, anti-injection) est faite par
`core.services.sql_guard.validate_select` AVANT exécution, et un timeout
applicatif borne les requêtes longues (SQLite n'a pas de statement_timeout).
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine

from core.services.sql_guard import validate_select

logger = logging.getLogger(__name__)


class ReadOnlySqlAdapter:
    def __init__(self, db_path, timeout_seconds: float = 8.0, max_rows: int = 200):
        self._timeout = timeout_seconds
        self._max_rows = max_rows
        abs_uri = "file:" + urllib.parse.quote(Path(db_path).resolve().as_posix())
        self._engine = create_async_engine(
            f"sqlite+aiosqlite:///{abs_uri}?mode=ro&uri=true",
            connect_args={"uri": True, "timeout": 30, "check_same_thread": False},
        )

        @event.listens_for(self._engine.sync_engine, "connect")
        def _read_only(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA query_only=ON")     # défense en profondeur (rejet DML)
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    async def query(self, sql: str, allowed_tables: set[str]) -> dict:
        """
        Valide puis exécute un SELECT borné à `allowed_tables`. Renvoie
        {sql_execute, colonnes, nb_lignes, resultats, tronque}.
        Lève SqlGuardError si la requête viole un garde-fou.
        """
        safe_sql = validate_select(sql, allowed_tables, max_limit=self._max_rows)

        async def _run():
            async with self._engine.connect() as conn:
                result = await conn.execute(text(safe_sql))
                columns = list(result.keys())
                rows = result.fetchmany(self._max_rows)
            return columns, rows

        columns, rows = await asyncio.wait_for(_run(), timeout=self._timeout)
        data = [
            {c: (str(v) if v is not None else None) for c, v in zip(columns, row)}
            for row in rows
        ]
        return {
            "sql_execute": safe_sql,
            "colonnes": columns,
            "nb_lignes": len(data),
            "resultats": data,
            "tronque": len(data) >= self._max_rows,
        }

    async def dispose(self) -> None:
        await self._engine.dispose()
