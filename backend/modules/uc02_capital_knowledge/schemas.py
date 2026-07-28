from pydantic import BaseModel
from typing import Optional


class ConversationTurnSchema(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    text: str
    history: list[ConversationTurnSchema] = []
    session_id: Optional[str] = None


class SourceSchema(BaseModel):
    doc_id: str
    filename: str
    doc_type: str
    excerpt: str
    relevance_score: float


class ChatResponse(BaseModel):
    answer: str
    intent: str
    sources: list[SourceSchema]
    tokens_used: int = 0
