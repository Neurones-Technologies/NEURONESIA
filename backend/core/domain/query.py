from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.domain.document import Source


class QueryIntent(str, Enum):
    RAG = "rag"
    LOCAL_DB = "local_db"
    HYBRID = "hybrid"


@dataclass
class ConversationTurn:
    role: str
    content: str


@dataclass
class UserQuery:
    text: str
    history: list[ConversationTurn] = field(default_factory=list)
    session_id: Optional[str] = None
    user_id: Optional[str] = None


@dataclass
class QueryResult:
    answer: str
    intent: QueryIntent
    sources: list[Source] = field(default_factory=list)
    tokens_used: int = 0
    cached: bool = False
