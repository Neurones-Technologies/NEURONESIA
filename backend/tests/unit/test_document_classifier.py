"""Tests du DocumentClassifier — règles rapides + fallback LLM (Phase 1)."""
import asyncio

from core.domain.document import DocumentType
from core.services.document_classifier import DocumentClassifier


class FakeLLM:
    """classify() renvoie un libellé prédéfini ; lève si appelé alors qu'on
    s'attend à ce que les règles tranchent (count vérifié dans les tests)."""

    def __init__(self, label: str = "cv"):
        self.label = label
        self.calls = 0

    async def classify(self, text, categories, default=None):
        self.calls += 1
        return self.label


def _classify(clf, text, filename=None):
    return asyncio.run(clf.classify(text, filename))


def test_regles_attestation_bonne_execution():
    llm = FakeLLM()
    clf = DocumentClassifier(llm)
    t = _classify(clf, "ATTESTATION DE BONNE EXÉCUTION\nNous certifions que la société...")
    assert t == DocumentType.ABE
    assert llm.calls == 0  # tranché par les règles, sans appel LLM


def test_regles_pv_recette():
    clf = DocumentClassifier(FakeLLM())
    assert _classify(clf, "PROCÈS-VERBAL DE RECETTE provisoire du projet X") == DocumentType.PV_RECETTE


def test_regles_appel_offres():
    clf = DocumentClassifier(FakeLLM())
    assert _classify(clf, "Avis d'appel d'offres ouvert n°2024-07") == DocumentType.AO


def test_regles_via_nom_fichier():
    clf = DocumentClassifier(FakeLLM())
    assert _classify(clf, "contenu neutre", filename="CV_Jean_Kouassi.pdf") == DocumentType.CV


def test_fallback_llm_quand_regles_muettes():
    llm = FakeLLM(label="certification")
    clf = DocumentClassifier(llm)
    t = _classify(clf, "Document sans marqueur reconnaissable par les règles.")
    assert t == DocumentType.CERTIFICATION
    assert llm.calls == 1  # le LLM a bien été sollicité


def test_fallback_label_inconnu_renvoie_unknown():
    clf = DocumentClassifier(FakeLLM(label="n_importe_quoi"))
    assert _classify(clf, "Texte ambigu sans marqueur.") == DocumentType.UNKNOWN
