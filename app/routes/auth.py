import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# In-memory session store — sessions survive until the process restarts.
_sessions: set[str] = set()


def is_authenticated(request: Request) -> bool:
    """Check if the request has a valid session cookie."""
    if not settings.auth_password:
        return True  # Auth disabled when no password is configured
    token = request.cookies.get("session")
    return token in _sessions


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login(request: Request, password: str = Form(...)):
    if secrets.compare_digest(password, settings.auth_password):
        token = secrets.token_urlsafe(32)
        _sessions.add(token)
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            key="session",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=30 * 24 * 3600,  # 30 days
        )
        return response

    return templates.TemplateResponse(
        request, "login.html", {"error": "Invalid password"}, status_code=401
    )


@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    if token:
        _sessions.discard(token)
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session")
    return response
