"""Outils de latence présale : empreinte de cache, purge LRU, timeout dur."""
import asyncio
import os

import pytest

from modules.uc10_presales.latency import content_key, prune_cache_dir, with_timeout


def test_content_key_deterministe_et_distinct():
    assert content_key("a", "b", 1) == content_key("a", "b", 1)
    assert content_key("a", "b") != content_key("a", "c")
    assert content_key(None) == content_key(None)


def test_prune_cache_dir_garde_les_plus_recents(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"f{i}.json"
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (1_000_000 + i * 100, 1_000_000 + i * 100))  # mtime croissant
        paths.append(p)
    deleted = prune_cache_dir(tmp_path, max_files=2)
    assert deleted == 3
    survivants = {p.name for p in tmp_path.glob("*.json")}
    assert survivants == {"f3.json", "f4.json"}  # les 2 plus récents


def test_prune_cache_dir_noop_si_sous_le_seuil(tmp_path):
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    assert prune_cache_dir(tmp_path, max_files=10) == 0
    assert prune_cache_dir(tmp_path, max_files=0) == 0  # purge désactivée


def test_with_timeout_sans_limite_renvoie_le_resultat():
    async def coro():
        return 42
    assert asyncio.run(with_timeout(coro(), "x", seconds=0)) == 42


def test_with_timeout_coupe_au_dela_de_la_limite():
    async def lent():
        await asyncio.sleep(1.0)
        return "trop tard"
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(with_timeout(lent(), "x", seconds=0.05))
