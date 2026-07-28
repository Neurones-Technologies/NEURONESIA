"""Endpoints matrice de conformité (assess → get → confirm) — cycle complet sans LLM/conteneur.

On monte UNIQUEMENT le router présale sur une app FastAPI nue (ces 3 endpoints n'utilisent
ni le conteneur ni le LLM : build_matrice + assess déterministe + persistance). Le store est
redirigé vers un dossier temporaire."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.uc10_presales.router import router
from modules.uc10_presales import matrix_store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(matrix_store, "_default_base", lambda: tmp_path)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _scoring_payload():
    return {
        "ao_filename": "AO démo conformité.pdf",
        "summary": "Refonte du SI",
        "key_elements": [],
        "matched_documents": [],
        "gaps_analysis": "",
        "strengths": ["Expertise Odoo multi-sociétés confirmée"],
        "risks": [],
        "score": 65,
        "recommendation": "GO",
        "justification": "",
        "besoins": [{"texte": "Expertise Odoo multi-sociétés requise", "source_section": "Art. 2"}],
    }


def test_cycle_assess_get_confirm(client):
    # 1) ASSESS : construit la matrice + pré-statut IA + persiste.
    r = client.post("/presales/matrix/assess",
                    json={"scoring_result": _scoring_payload(), "client_name": "BGFI"})
    assert r.status_code == 200, r.text
    matrice = r.json()
    assert matrice["total"] if "total" in matrice else len(matrice["exigences"]) >= 1
    ex = matrice["exigences"][0]
    assert ex["statut_suggere"] == "CONFORME"        # dérivé de la force "Expertise Odoo"
    assert ex["justification_ia"]
    assert ex["statut_conformite"] == "A_TRAITER"     # l'IA ne valide jamais seule
    assert ex["confirme"] is False

    # 2) GET : recharge la matrice persistée.
    g = client.get("/presales/matrix", params={"ao_filename": "AO démo conformité.pdf"})
    assert g.status_code == 200
    assert len(g.json()["exigences"]) == len(matrice["exigences"])

    # 3) CONFIRM : cochage humain → statut validé + traçabilité.
    c = client.post("/presales/matrix/confirm", json={
        "ao_filename": "AO démo conformité.pdf",
        "confirme_par": "akouadjo@neuronestech.com",
        "confirmations": [{"id": ex["id"], "statut_confirme": "CONFORME"}],
    })
    assert c.status_code == 200, c.text
    assert c.json()["confirmes"] == 1

    # 4) GET : la confirmation humaine a bien été persistée.
    g2 = client.get("/presales/matrix", params={"ao_filename": "AO démo conformité.pdf"}).json()
    e0 = g2["exigences"][0]
    assert e0["statut_conformite"] == "CONFORME"
    assert e0["confirme"] is True
    assert e0["confirme_par"] == "akouadjo@neuronestech.com"
    assert e0["confirme_le"]


def test_get_absent_renvoie_404(client):
    assert client.get("/presales/matrix", params={"ao_filename": "jamais.pdf"}).status_code == 404


def test_confirm_sans_assess_renvoie_404(client):
    r = client.post("/presales/matrix/confirm",
                    json={"ao_filename": "jamais.pdf", "confirmations": []})
    assert r.status_code == 404
