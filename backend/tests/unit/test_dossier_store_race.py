"""dossier_store.patch() — un `analyze` en arrière-plan qui persiste son résultat
juste après que l'utilisateur a supprimé le dossier depuis l'UI faisait remonter
une StaleDataError (0 ligne mise à jour) en 500, réellement observée en prod
(DELETE 200 puis PATCH 500 sur le même dossier). Un dossier supprimé n'a plus
besoin de son résultat : `patch()` doit l'ignorer silencieusement (renvoyer None),
pas planter."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from sqlalchemy.orm.exc import StaleDataError

import modules.uc10_presales.dossier_store as dossier_store


class _FakeSession:
    def __init__(self, row, commit_exc=None):
        self._row = row
        self._commit_exc = commit_exc
        self.rolled_back = False

    async def get(self, model, dossier_id):
        return self._row

    async def commit(self):
        if self._commit_exc is not None:
            raise self._commit_exc

    async def rollback(self):
        self.rolled_back = True


def _fake_session_factory(session):
    @asynccontextmanager
    async def factory():
        yield session
    return factory


def test_patch_ignore_stale_data_error_dossier_supprime(monkeypatch):
    row = SimpleNamespace(state={"status": "scoring"}, client_name="", owner="", deadline="", status="scoring")
    session = _FakeSession(row, commit_exc=StaleDataError("mismatch", 1, 0))
    monkeypatch.setattr(dossier_store, "AsyncSessionLocal", _fake_session_factory(session))

    result = asyncio.run(dossier_store.patch("dossier-supprime", {"status": "scored"}))

    assert result is None
    assert session.rolled_back is True


def test_patch_reussit_normalement_sans_race(monkeypatch):
    row = SimpleNamespace(state={"status": "scoring"}, client_name="", owner="", deadline="", status="scoring")
    session = _FakeSession(row, commit_exc=None)
    monkeypatch.setattr(dossier_store, "AsyncSessionLocal", _fake_session_factory(session))

    result = asyncio.run(dossier_store.patch("dossier-normal", {"status": "scored"}))

    assert result == {"status": "scored"}
