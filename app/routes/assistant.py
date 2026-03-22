import uuid
from datetime import date, datetime

from fastapi import APIRouter, Form, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select

from app.database import async_session
from app.models.conversation import Conversation, UsageLog
from app.services.assistant import fantasy_assistant

router = APIRouter(prefix="/api/assistant")
templates = Jinja2Templates(directory="app/templates")


@router.post("/ask")
async def ask(
    request: Request,
    message: str = Form(...),
    session_id: str = Form(""),
):
    """Send a message to the assistant. Returns an HTMX partial."""
    if not session_id:
        session_id = str(uuid.uuid4())

    result = await fantasy_assistant.ask(session_id, message.strip())

    return templates.TemplateResponse(
        request,
        "partials/chat_message.html",
        {
            "user_message": message.strip(),
            "response": result["answer"],
            "session_id": result["session_id"],
            "tools_used": result["tools_used"],
        },
    )


@router.get("/history/{session_id}")
async def get_history(request: Request, session_id: str):
    """Load conversation history for a session."""
    async with async_session() as session:
        result = await session.execute(
            select(Conversation)
            .where(Conversation.session_id == session_id)
            .order_by(Conversation.created_at)
        )
        messages = result.scalars().all()

    return templates.TemplateResponse(
        request,
        "partials/chat_history.html",
        {"messages": messages, "session_id": session_id},
    )


@router.delete("/history/{session_id}")
async def delete_history(session_id: str):
    """Clear conversation history for a session."""
    async with async_session() as session:
        await session.execute(delete(Conversation).where(Conversation.session_id == session_id))
        await session.commit()
    return {"status": "cleared"}


@router.get("/usage")
async def get_usage():
    """Get token usage statistics."""
    async with async_session() as session:
        today_start = datetime.combine(date.today(), datetime.min.time())

        # Today's usage
        result = await session.execute(
            select(
                func.coalesce(func.sum(UsageLog.input_tokens), 0),
                func.coalesce(func.sum(UsageLog.output_tokens), 0),
                func.count(UsageLog.id),
            ).where(UsageLog.created_at >= today_start)
        )
        today = result.one()

        # All-time usage
        result = await session.execute(
            select(
                func.coalesce(func.sum(UsageLog.input_tokens), 0),
                func.coalesce(func.sum(UsageLog.output_tokens), 0),
                func.count(UsageLog.id),
            )
        )
        total = result.one()

        from app.config import settings

        daily_limit = settings.assistant_daily_token_limit
        today_total = today[0] + today[1]

        return {
            "today": {
                "input_tokens": today[0],
                "output_tokens": today[1],
                "requests": today[2],
                "total_tokens": today_total,
            },
            "all_time": {
                "input_tokens": total[0],
                "output_tokens": total[1],
                "requests": total[2],
            },
            "daily_limit": daily_limit,
            "pct_used": round(today_total / daily_limit * 100, 1) if daily_limit else 0,
        }
