import logging

from core.domain.query import UserQuery, QueryResult, ConversationTurn
from core.services.query_dispatcher import QueryDispatcher

logger = logging.getLogger(__name__)


class CapitalKnowledgeUseCase:
    """
    UC02 — Chat RAG interne.
    L'utilisateur pose des questions en français.
    Le dispatcher route vers RAG, LocalDB ou les deux.
    L'historique est tronqué à max_history_turns tours.
    """

    def __init__(self, dispatcher: QueryDispatcher):
        self._dispatcher = dispatcher

    async def query(
        self,
        text: str,
        history: list[dict],
        session_id: str | None = None,
    ) -> QueryResult:
        turns = [ConversationTurn(role=t["role"], content=t["content"]) for t in history]
        user_query = UserQuery(text=text, history=turns, session_id=session_id)
        return await self._dispatcher.dispatch(user_query)
