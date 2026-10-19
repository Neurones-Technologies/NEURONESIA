"""Isolation des tests vis-à-vis du dossier de données réel.

Les marqueurs de bascule nt360 (`bascule_nt360.json`, `indicateurs_base.json`)
vivent à côté de la base locale. Lus depuis le vrai dossier `data/local_db`,
ils changent le comportement des tests selon l'état de la machine — une base
de dev déjà basculée coupait les snapshots de pipeline d'un test qui n'avait
rien demandé. Chaque test part donc d'un état « jamais basculé ».
"""
import pytest

from modules.uc_briefing import bascule, indicateurs


@pytest.fixture(autouse=True)
def _marqueurs_nt360_isoles(tmp_path, monkeypatch):
    monkeypatch.setattr(bascule, "_FICHIER", tmp_path / "bascule_nt360.json")
    monkeypatch.setattr(indicateurs, "_MARQUEUR_BASE", tmp_path / "indicateurs_base.json")
    indicateurs.vider_cache_snapshots()
    yield
    indicateurs.vider_cache_snapshots()
