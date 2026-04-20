from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app import config
from app.schemas import ChatMessage, ChatSessionRequest, DiagnoseRequest, SummarizeRequest
from app.services.ai_service import chat_session_stream, chat_stream, diagnose_stream, summarize_plan_stream
from app.services.terraform_parser import load_project_context

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _sse_chunk(chunk: str) -> str:
    lines = chunk.split("\n")
    return "".join(f"data: {line}\n" for line in lines) + "\n"


@router.post("/chat")
async def chat(msg: ChatMessage):
    ai_config = config.get_ai_config()

    async def event_stream():
        async for chunk in chat_stream(msg.message, msg.context, ai_config):
            yield _sse_chunk(chunk)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/chat-session")
async def chat_session(req: ChatSessionRequest, request: Request):
    ai_config = config.get_ai_config()
    context = load_project_context(request.app.state.project_dir)

    async def event_stream():
        async for chunk in chat_session_stream(req.messages, context, ai_config):
            yield _sse_chunk(chunk)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/diagnose")
async def diagnose(req: DiagnoseRequest, request: Request):
    ai_config = config.get_ai_config()
    context = load_project_context(request.app.state.project_dir)

    async def event_stream():
        async for chunk in diagnose_stream(req.command, req.output, context, ai_config):
            yield _sse_chunk(chunk)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/summarize")
async def summarize(req: SummarizeRequest):
    ai_config = config.get_ai_config()

    async def event_stream():
        async for chunk in summarize_plan_stream(req.resources, ai_config):
            yield _sse_chunk(chunk)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
