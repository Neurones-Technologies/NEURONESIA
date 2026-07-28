from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class VeilleSourceCreate(BaseModel):
    name: str
    url: str
    feed_type: str = "rss"
    keywords: str = ""


class VeilleSourceOut(BaseModel):
    id: int
    name: str
    url: str
    feed_type: str
    keywords: str
    active: bool
    last_scan: Optional[datetime] = None

    class Config:
        from_attributes = True


class VeilleEntryOut(BaseModel):
    id: int
    source_id: Optional[int] = None
    title: str
    url: str
    description: str
    published_at: Optional[datetime] = None
    detected_at: datetime
    status: str
    estimated_budget: str
    deadline: str
    country: str
    relevance_score: int

    # Analyse IA S2I (agent Watch-Tracker) — vides si l'entrée n'a pas été traitée.
    ai_analyzed: bool = False
    signal_label: str = ""
    risque: str = ""
    offre: str = ""
    offre_short: str = ""
    priority: str = ""
    criticite: int = 0
    organisation: str = ""
    justification: str = ""
    origin: str = "source"  # "source" (scan interne) | "web" (exploration Internet)
    debrief: str = ""       # débriefing pré-généré (affiché instantanément au clic)

    class Config:
        from_attributes = True


class VeilleEntryPatch(BaseModel):
    status: Optional[str] = None


class VeilleConfigOut(BaseModel):
    themes: str = ""
    web_search_enabled: bool = False

    class Config:
        from_attributes = True


class VeilleConfigPatch(BaseModel):
    themes: Optional[str] = None
    web_search_enabled: Optional[bool] = None
