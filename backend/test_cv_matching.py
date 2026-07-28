"""Test ciblé : vérifie la nouvelle recherche CV profil-par-profil (_match_cvs)
contre la GED réellement indexée (ChromaDB + BM25 + embeddings OpenAI).

Ne touche PAS au LLM (les étapes de scoring) : on isole la fouille GED.
Lance : python test_cv_matching.py
"""
import asyncio

from adapters.embeddings.sentence_transformers_adapter import SentenceTransformersAdapter
from adapters.vector_store.chromadb_adapter import ChromaDBAdapter
from adapters.sparse_search.bm25_adapter import BM25Adapter
from core.services.rag_engine import RAGEngine
from core.domain.offer import RequiredProfile
from modules.uc10_presales.scoring_pipeline import ScoringPipeline


# Profils représentatifs de l'AO démo BSIC (infra cloud bancaire)
PROFILS = [
    RequiredProfile(
        profil="Architecte Cloud", domaine="Infrastructure / Cloud", quantite=2,
        niveau="BAC+5 / Ingénieur", experience_min="5 ans",
        competences=["VMware vSphere", "Azure", "AWS", "Réseau & sécurité"],
        certifications=["VMware VCP", "Azure Solutions Architect"],
    ),
    RequiredProfile(
        profil="Ingénieur Virtualisation", domaine="Infrastructure", quantite=3,
        niveau="BAC+4", experience_min="3 ans",
        competences=["VMware", "Sauvegarde & restauration", "Scripting PowerShell"],
        certifications=["VMware VCP"],
    ),
    RequiredProfile(
        profil="Analyste Cybersécurité", domaine="Cybersécurité", quantite=1,
        niveau="Senior", experience_min="4 ans",
        competences=["SOC", "pare-feu", "audit sécurité"],
        certifications=["CEH", "CCNP Security"],
    ),
]


async def main():
    # Embedder LOCAL (384 dim) = celui qui a indexé la GED (cf. collection ChromaDB dim=384).
    rag = RAGEngine(
        vector_store=ChromaDBAdapter(),
        sparse_search=BM25Adapter(),
        embedder=SentenceTransformersAdapter(),
        llm=None,
    )
    pipeline = ScoringPipeline(llm=None, rag_engine=rag)

    print("=== _match_cvs (profil par profil) ===")
    cv_sources = await pipeline._match_cvs(PROFILS, [], "")
    print(f"\nRésultat : {len(cv_sources)} CV uniques\n")
    for s in cv_sources:
        print(f"  {s.relevance_score:.4f}  [{s.doc_type.value}]  {s.filename}")

    print("\n=== Comparaison : ancienne requête fusionnée ===")
    fused_query = " ".join(p.profil for p in PROFILS)
    old = await rag.search(query=fused_query, filter_metadata={"doc_type": "cv"}, top_k=6)
    print(f"Requête fusionnée → {len(old)} CV")
    for s in old:
        print(f"  {s.relevance_score:.4f}  {s.filename}")


if __name__ == "__main__":
    asyncio.run(main())
