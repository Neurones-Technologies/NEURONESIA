from fastapi import APIRouter, Request
from modules._template.schemas import UCXXRequest, UCXXResponse

router = APIRouter(prefix="/ucxx", tags=["UCXX - Nom du module"])


@router.post("/action", response_model=UCXXResponse)
async def ucxx_action(body: UCXXRequest, request: Request):
    # container = request.app.state.container
    # use_case = UCXXUseCase(llm=container.llm_haiku, rag_engine=container.rag_engine)
    # result = await use_case.execute(body.model_dump())
    return UCXXResponse(result="TODO")
