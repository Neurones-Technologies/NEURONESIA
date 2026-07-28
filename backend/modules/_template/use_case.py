"""
TEMPLATE — Copier ce dossier pour créer un nouveau Use Case.
Remplacer UCXX_NOM par le nom réel (ex: uc06_financial).

Convention :
- Le use case ne connaît QUE les ports (interfaces) — jamais les adapters
- Les ports sont injectés via le Container (config/container.py)
- Ajouter le router dans api/v1/__init__.py
"""
import logging

logger = logging.getLogger(__name__)


class UCXXUseCase:
    """
    UCXX — Description du use case.
    """

    def __init__(self, llm, rag_engine):
        self._llm = llm
        self._rag_engine = rag_engine

    async def execute(self, input_data: dict) -> dict:
        raise NotImplementedError("Implémenter la logique métier ici")
