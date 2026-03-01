from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class BardPushReq(BaseModel):
    line_user_id: str
    raw_item_id: int
    display_name: Optional[str] = None
    send: bool = True


class BardPushOut(BaseModel):
    user_id: int
    agent_run_id: int
    push_message_id: int
    delivery_status: str
    line_request_id: Optional[str] = None
    message_preview: str


class LorekeeperAskReq(BaseModel):
    line_user_id: str
    question: str = Field(min_length=1, max_length=2000)
    display_name: Optional[str] = None
    rag_space_key: str = "default"


class LorekeeperAskOut(BaseModel):
    user_id: int
    query_id: int
    status: str
    answer: Optional[str] = None
    rejected_reason: Optional[str] = None
    usage: Dict[str, Any]
