from typing import Annotated

from pydantic import Field, StringConstraints

from app.schemas.user import StrictRequest


class KnowledgeSearchRequest(StrictRequest):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    top_k: Annotated[int, Field(strict=True, ge=1, le=10)] = 5
