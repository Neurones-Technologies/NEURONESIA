"""Bascule du pipeline Odoo → nt360 : aucune comparaison de snapshots ne doit
la traverser — une photo Odoo face à une photo nt360 fabrique des mouvements
qui n'ont jamais eu lieu (1 230 opportunités « disparues »)."""
import asyncio
import json
from datetime import date

from modules.uc_briefing import bascule, evenements, indicateurs


def test_date_absente_tant_que_non_basculee(tmp_path, monkeypatch):
    monkeypatch.setattr(bascule, "_FICHIER", tmp_path / "bascule_nt360.json")
    assert bascule.date_opportunites() is None


def test_bornes_de_snapshot_ne_traversent_pas_la_bascule(tmp_path, monkeypatch):
    fichier = tmp_path / "bascule_nt360.json"
    fichier.write_text(json.dumps({"opportunites": "2026-10-20"}))
    monkeypatch.setattr(bascule, "_FICHIER", fichier)

    class Session:
        def __init__(self, valeurs): self.valeurs = iter(valeurs)
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, *a, **k):
            v = next(self.valeurs)
            class R:
                def scalar(self_inner): return v
            return R()

    def fabrique(valeurs):
        return lambda: Session(valeurs)

    # fin = 21/10 (nt360), début = 19/10 (Odoo) : la différence traverserait la bascule
    monkeypatch.setattr(evenements, "AsyncSessionLocal", fabrique(["2026-10-21", "2026-10-19"]))
    assert asyncio.run(evenements._bornes_snapshot(date(2026, 10, 21), date(2026, 10, 21))) is None
    # début = 20/10 et fin = 22/10 : les deux photos sont nt360
    monkeypatch.setattr(evenements, "AsyncSessionLocal", fabrique(["2026-10-22", "2026-10-20"]))
    assert asyncio.run(evenements._bornes_snapshot(date(2026, 10, 22), date(2026, 10, 22))) == (
        date(2026, 10, 20), date(2026, 10, 22))


def test_jours_de_snapshot_anterieurs_a_la_bascule_ignores(tmp_path, monkeypatch):
    fichier = tmp_path / "bascule_nt360.json"
    fichier.write_text(json.dumps({"opportunites": "2026-10-20"}))
    monkeypatch.setattr(bascule, "_FICHIER", fichier)

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def execute(self, *a, **k):
            class R:
                def all(self_inner): return [("2026-10-18",), ("2026-10-19",), ("2026-10-20",), ("2026-10-21",)]
            return R()

    monkeypatch.setattr(indicateurs, "AsyncSessionLocal", lambda: Session())
    indicateurs.vider_cache_snapshots()
    try:
        jours = asyncio.run(indicateurs._jours_snapshotes("pipeline_snapshots"))
        assert jours == {date(2026, 10, 20), date(2026, 10, 21)}
    finally:
        indicateurs.vider_cache_snapshots()
