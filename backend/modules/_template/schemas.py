from pydantic import BaseModel


class UCXXRequest(BaseModel):
    """Schéma d'entrée du use case."""
    data: str


class UCXXResponse(BaseModel):
    """Schéma de sortie du use case."""
    result: str
