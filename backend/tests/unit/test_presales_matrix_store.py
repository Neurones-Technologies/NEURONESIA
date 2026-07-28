"""Persistance de la matrice de conformité (clôture C5) — round-trip + cochage humain."""
from core.domain.requirements import (
    Exigence, MatriceConformite, STATUT_CONFORME, STATUT_NON_CONFORME,
)
from modules.uc10_presales import matrix_store


def _matrice():
    return MatriceConformite(ao_filename="AO démo.pdf", exigences=[
        Exigence(id="EX-0001", texte="exigence 1", statut_suggere=STATUT_CONFORME),
        Exigence(id="EX-0002", texte="exigence 2"),
    ], expected_total=2)


def test_save_then_load_roundtrip(tmp_path):
    m = _matrice()
    matrix_store.save(m, base=tmp_path)
    loaded = matrix_store.load("AO démo.pdf", base=tmp_path)
    assert loaded is not None
    assert loaded.total == 2
    assert loaded.exigences[0].statut_suggere == STATUT_CONFORME


def test_load_absent_renvoie_none(tmp_path):
    assert matrix_store.load("inconnu.pdf", base=tmp_path) is None


def test_apply_confirmations_fige_le_controle_humain():
    m = _matrice()
    matrix_store.apply_confirmations(
        m,
        [{"id": "EX-0001", "statut_confirme": "CONFORME", "commentaire": "PV vérifié"},
         {"id": "EX-0002", "statut_confirme": "NON_CONFORME"}],
        confirme_par="akouadjo@neuronestech.com", now_iso="2026-06-29T10:00:00",
    )
    e1, e2 = m.exigences
    assert e1.statut_conformite == STATUT_CONFORME and e1.confirme is True
    assert e1.confirme_par == "akouadjo@neuronestech.com" and e1.confirme_le.startswith("2026")
    assert e1.commentaire == "PV vérifié"
    assert e2.statut_conformite == STATUT_NON_CONFORME and e2.confirme is True


def test_decocher_leve_la_confirmation():
    m = _matrice()
    matrix_store.apply_confirmations(m, [{"id": "EX-0001", "confirme": True, "statut_confirme": "CONFORME"}],
                                     now_iso="2026-06-29T10:00:00")
    matrix_store.apply_confirmations(m, [{"id": "EX-0001", "confirme": False}])
    assert m.exigences[0].confirme is False
    assert m.exigences[0].statut_conformite == "A_TRAITER"


def test_confirm_sans_matrice_persistee_renvoie_none(tmp_path):
    assert matrix_store.confirm("jamais_vu.pdf", [], base=tmp_path) is None


def test_confirm_charge_merge_et_repersiste(tmp_path):
    matrix_store.save(_matrice(), base=tmp_path)
    out = matrix_store.confirm(
        "AO démo.pdf", [{"id": "EX-0001", "statut_confirme": "CONFORME"}],
        confirme_par="h", now_iso="2026-06-29T11:00:00", base=tmp_path,
    )
    assert out is not None and out.exigences[0].confirme is True
    # La persistance a bien été ré-écrite.
    reloaded = matrix_store.load("AO démo.pdf", base=tmp_path)
    assert reloaded.exigences[0].statut_conformite == STATUT_CONFORME
