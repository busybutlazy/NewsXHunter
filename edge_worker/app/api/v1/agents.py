from fastapi import APIRouter, HTTPException

from app.adapters.repos.agent_run_repo import AgentRunRepo
from app.adapters.repos.line_delivery_repo import LineDeliveryRepo
from app.adapters.repos.user_query_repo import UserQueryRepo
from app.api.v1.schemas.agents import BardPushOut, BardPushReq, LorekeeperAskOut, LorekeeperAskReq
from app.services.bard_agent_service import BardAgentService
from app.services.lorekeeper_agent_service import LorekeeperAgentService


router = APIRouter()


def build_bard_service() -> BardAgentService:
    return BardAgentService(
        line_repo=LineDeliveryRepo(),
        run_repo=AgentRunRepo(),
    )


def build_lorekeeper_service() -> LorekeeperAgentService:
    return LorekeeperAgentService(
        query_repo=UserQueryRepo(),
        run_repo=AgentRunRepo(),
    )


@router.post("/bard/push", response_model=BardPushOut)
def bard_push(req: BardPushReq):
    try:
        service = build_bard_service()
        result = service.create_push_and_deliver(
            line_user_id=req.line_user_id,
            raw_item_id=req.raw_item_id,
            display_name=req.display_name,
            send=req.send,
        )
        return BardPushOut(**result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/lorekeeper/ask", response_model=LorekeeperAskOut)
def lorekeeper_ask(req: LorekeeperAskReq):
    try:
        service = build_lorekeeper_service()
        result = service.ask(
            line_user_id=req.line_user_id,
            question=req.question,
            display_name=req.display_name,
            rag_space_key=req.rag_space_key,
        )
        return LorekeeperAskOut(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
