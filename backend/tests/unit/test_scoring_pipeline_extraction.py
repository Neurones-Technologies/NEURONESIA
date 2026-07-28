"""ScoringPipeline — retry sur troncature (step1.extract) et repli grille dégénérée
(step1b.frame). Bug réel trouvé en testant un AO dense (97 pages) : le JSON tronqué
faisait perdre TOUS les besoins/critères en silence, et une grille extraite mais sans
le moindre point chiffré n'était jamais remplacée par le repli standard."""
import asyncio

from core.domain.offer import ScoringCriterion
from core.ports.llm_gateway import OutputTruncatedError
from modules.uc10_presales.scoring_pipeline import ScoringPipeline

# `data/scoring_grids/regie_it.yaml` n'est pas versionné (data/ est dans .gitignore/
# .dockerignore) — absent de cet environnement de test. On fournit une grille standard
# synthétique équivalente plutôt que de dépendre d'un fichier externe non garanti présent.
_FAKE_STANDARD_GRID = [
    ScoringCriterion(id="std-1", label="Expérience", max_points=30, category="Technique", is_inferred=True),
    ScoringCriterion(id="std-2", label="Prix", max_points=40, category="Financier", is_inferred=True),
    ScoringCriterion(id="std-3", label="Méthodologie", max_points=30, category="Technique", is_inferred=True),
]


class FakeLLM:
    """`extract`/`generate` rejouent une séquence de réponses programmées (succès ou
    troncature) — permet de simuler un premier essai tronqué puis un retry réussi."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.max_tokens_seen = []

    async def extract(self, prompt, text, max_tokens=512, raise_on_truncation=False, temperature=None, cacheable=False):
        self.max_tokens_seen.append(max_tokens)
        outcome = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        if outcome == "TRUNCATED":
            if raise_on_truncation:
                raise OutputTruncatedError(partial_text="", max_tokens=max_tokens)
            return ""
        if outcome == "SDK_VALUE_ERROR":
            # Simule le refus du SDK Anthropic d'exécuter un appel non-streaming dont
            # max_tokens dépasse son plafond interne (~21333) — une pure ValueError levée
            # AVANT tout appel réseau, distincte d'une troncature ou d'un JSON malformé.
            raise ValueError("Streaming is required for operations that may take longer than 10 minutes.")
        return outcome

    async def generate(self, system, user, max_tokens=1024, raise_on_truncation=False, temperature=None, cacheable=False):
        return await self.extract(system, user, max_tokens, raise_on_truncation, temperature, cacheable)

    def count_tokens(self, text: str) -> int:
        return len(text) // 4  # estimation grossière, suffisante pour ces tests


def _pipeline(llm) -> ScoringPipeline:
    return ScoringPipeline(llm=llm, rag_engine=None)


def test_step1_extract_retente_a_budget_elargi_si_tronque():
    # step1.extract lance 2 appels concurrents par chunk (besoins+key_points, puis le reste
    # — cf. _EXTRACT_SYSTEM_BESOINS/_EXTRACT_SYSTEM_AUTRES) : le 1er (besoins) est tronqué
    # puis retenté avec succès, le 2e (autres) réussit du premier coup.
    ok_besoins = '{"key_points": [], "besoins": [{"texte": "Migration Odoo", "source_section": "3.1"}]}'
    ok_autres = '{"criteres_selection": [], "prerequis": [], "ressources_demandees": [], "points_vigilance": [], "date_remise": ""}'
    llm = FakeLLM(["TRUNCATED", ok_besoins, ok_autres])
    pipeline = _pipeline(llm)

    elements, extra = asyncio.run(pipeline._step1_extract("texte de l'AO"))

    assert llm.calls == 3  # besoins : tronqué puis retry réussi ; autres : réussi direct
    assert llm.max_tokens_seen[1] > llm.max_tokens_seen[0]  # budget élargi au retry besoins
    assert len(extra["besoins"]) == 1
    assert extra["besoins"][0].texte == "Migration Odoo"


def test_step1_extract_vide_honnetement_si_toujours_tronque():
    llm = FakeLLM(["TRUNCATED", "TRUNCATED"])
    pipeline = _pipeline(llm)

    elements, extra = asyncio.run(pipeline._step1_extract("texte de l'AO"))

    assert llm.calls == 4  # 2 essais (base+retry) x 2 appels concurrents (besoins+autres)
    assert elements == []
    assert extra["besoins"] == []  # honnête : vide, pas de contenu inventé


def test_step1_extract_retente_si_json_malforme_non_tronque():
    # Réponse COMPLÈTE (pas de troncature) mais syntaxiquement invalide — cas réel observé
    # en prod ("Expecting ',' delimiter") sur un AO dense, distinct d'une troncature.
    malformed = '{"key_points": [], "besoins": [{"texte": "A" "source_section": "1"}]}'
    ok_besoins = '{"key_points": [], "besoins": [{"texte": "Migration Odoo", "source_section": "3.1"}]}'
    ok_autres = '{"criteres_selection": [], "prerequis": [], "ressources_demandees": [], "points_vigilance": [], "date_remise": ""}'
    llm = FakeLLM([malformed, ok_besoins, ok_autres])
    pipeline = _pipeline(llm)

    elements, extra = asyncio.run(pipeline._step1_extract("texte de l'AO"))

    assert llm.calls == 3
    assert len(extra["besoins"]) == 1
    assert extra["besoins"][0].texte == "Migration Odoo"


def test_step1_extract_vide_honnetement_si_json_toujours_malforme():
    malformed = '{"key_points": [], "besoins": [{"texte": "A" "source_section": "1"}]}'
    llm = FakeLLM([malformed, malformed])
    pipeline = _pipeline(llm)

    elements, extra = asyncio.run(pipeline._step1_extract("texte de l'AO"))

    assert llm.calls == 4  # 2 essais x 2 appels concurrents, tous malformés
    assert extra["besoins"] == []


def test_step1_extract_echec_partiel_ne_perd_que_la_moitie_en_echec():
    # Le point central du split : si l'appel "besoins" échoue mais "autres" réussit (ou
    # inversement), on ne perd plus TOUT le chunk — seulement la moitié en échec (avant le
    # split : un seul appel portait tout, un échec perdait besoins ET critères ET tout le reste).
    ok_autres = '{"criteres_selection": [{"texte": "Critère X", "source_section": "2"}], "prerequis": [], "ressources_demandees": [], "points_vigilance": [], "date_remise": ""}'
    llm = FakeLLM(["TRUNCATED", "TRUNCATED", ok_autres])
    pipeline = _pipeline(llm)

    elements, extra = asyncio.run(pipeline._step1_extract("texte de l'AO"))

    assert extra["besoins"] == []  # moitié en échec : vide, honnête
    assert len(extra["criteres_selection"]) == 1  # moitié réussie : conservée
    assert extra["criteres_selection"][0].texte == "Critère X"


def test_step1_extract_retente_si_sdk_refuse_appel_non_streaming():
    # Bug réel en prod : le SDK Anthropic lève une ValueError (pas OutputTruncatedError)
    # quand max_tokens dépasse son plafond non-streaming interne — AVANT tout appel réseau.
    # Sans gestion dédiée, cette exception remontait et faisait planter TOUT le pipeline.
    ok_besoins = '{"key_points": [], "besoins": [{"texte": "Migration Odoo", "source_section": "3.1"}]}'
    ok_autres = '{"criteres_selection": [], "prerequis": [], "ressources_demandees": [], "points_vigilance": [], "date_remise": ""}'
    llm = FakeLLM(["SDK_VALUE_ERROR", ok_besoins, ok_autres])
    pipeline = _pipeline(llm)

    elements, extra = asyncio.run(pipeline._step1_extract("texte de l'AO"))

    assert llm.calls == 3  # besoins : refusé par le SDK puis retry réussi ; autres : réussi direct
    assert len(extra["besoins"]) == 1
    assert extra["besoins"][0].texte == "Migration Odoo"


def test_step1_extract_vide_honnetement_si_sdk_refuse_toujours(monkeypatch):
    # Le refus SDK persiste sur les DEUX tentatives (ex. budget de retry mal réglé à nouveau
    # au-dessus du plafond) : on abandonne PROPREMENT cette partie plutôt que de laisser
    # l'exception remonter et casser le pipeline entier — pas d'exception levée par ce test.
    llm = FakeLLM(["SDK_VALUE_ERROR", "SDK_VALUE_ERROR"])
    pipeline = _pipeline(llm)

    elements, extra = asyncio.run(pipeline._step1_extract("texte de l'AO"))

    assert llm.calls == 4  # 2 essais x 2 appels concurrents, tous refusés par le SDK
    assert extra["besoins"] == []  # honnête : vide, pas de crash


def test_step1_extract_multi_chunk_fusionne_et_deduplique(monkeypatch):
    # AO dense (SIB 97p, BHCI...) : un seul appel JSON n'y suffit pas (trop de besoins/
    # critères pour tenir dans le plafond de sortie, même élargi). Map-reduce : découpe en
    # chunks, extraction en parallèle, fusion en dédupliquant les items qui ressortent dans
    # le recouvrement entre deux chunks. Seuils de chunking abaissés ici pour forcer le
    # découpage sans dépendre d'un vrai texte de dizaines de milliers de caractères.
    import modules.uc10_presales.scoring_pipeline as sp
    monkeypatch.setattr(sp, "_EXTRACT_CHUNK_SIZE_TOKENS", 5)
    monkeypatch.setattr(sp, "_EXTRACT_CHUNK_OVERLAP_TOKENS", 0)

    # Chaque chunk fait 2 appels concurrents (besoins, puis autres) : 2 chunks x 2 = 4 réponses.
    chunk1_besoins = '{"key_points": [], "besoins": [{"texte": "Besoin A", "source_section": "1"}]}'
    chunk1_autres = '{"criteres_selection": [], "prerequis": [], "ressources_demandees": [], "points_vigilance": [], "date_remise": "2026-01-01"}'
    chunk2_besoins = '{"key_points": [], "besoins": [{"texte": "Besoin A", "source_section": "1"}, {"texte": "Besoin B", "source_section": "2"}]}'
    chunk2_autres = '{"criteres_selection": [], "prerequis": [], "ressources_demandees": [], "points_vigilance": [], "date_remise": ""}'
    llm = FakeLLM([chunk1_besoins, chunk1_autres, chunk2_besoins, chunk2_autres])
    pipeline = _pipeline(llm)

    elements, extra = asyncio.run(pipeline._step1_extract("x" * 30))

    assert llm.calls == 4  # 2 chunks x 2 appels concurrents chacun
    texts = {b.texte for b in extra["besoins"]}
    assert texts == {"Besoin A", "Besoin B"}  # "Besoin A" dédupliqué malgré 2 occurrences
    assert extra["date_remise"] == "2026-01-01"  # premier date_remise non vide conservé


def test_frame_grille_degeneree_retombe_sur_grille_standard(monkeypatch):
    # Critères extraits (liste non vide) mais tous à 0 point — cas réel rencontré sur
    # un AO qui décrit ses critères en prose sans grille pondérée explicite.
    monkeypatch.setattr(ScoringPipeline, "_load_standard_grid", staticmethod(lambda doc_type="regie_it": _FAKE_STANDARD_GRID))
    degenerate = (
        '{"market_identity": {}, "calendar": [], "evaluation_modalities": {},'
        ' "criteria": [{"id": "1", "label": "Expérience", "max_points": 0, "category": "Technique"},'
        ' {"id": "2", "label": "Méthodologie", "max_points": 0, "category": "Technique"}]}'
    )
    llm = FakeLLM([degenerate])
    pipeline = _pipeline(llm)

    _, _, _, criteria = asyncio.run(pipeline._step1b_extract_frame("texte de l'AO"))

    assert criteria == _FAKE_STANDARD_GRID  # grille standard, pas la dégénérée
    assert all(c.is_inferred for c in criteria)  # jamais présentée comme vérité de l'AO


def test_frame_grille_verbatim_avec_points_reels_est_conservee():
    real = (
        '{"market_identity": {}, "calendar": [], "evaluation_modalities": {},'
        ' "criteria": [{"id": "1", "label": "Prix", "max_points": 40, "category": "Financier"},'
        ' {"id": "2", "label": "Technique", "max_points": 60, "category": "Technique"}]}'
    )
    llm = FakeLLM([real])
    pipeline = _pipeline(llm)

    _, _, _, criteria = asyncio.run(pipeline._step1b_extract_frame("texte de l'AO"))

    assert sum(c.max_points for c in criteria) == 100
    labels = {c.label for c in criteria}
    assert labels == {"Prix", "Technique"}
