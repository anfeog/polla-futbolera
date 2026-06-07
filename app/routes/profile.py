from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.auth import require_login
from app.templating import templates
from app.avatars import AVATARS, is_valid

router = APIRouter()


@router.get("/perfil", response_class=HTMLResponse)
def profile(request: Request, user=Depends(require_login)):
    return templates.TemplateResponse("perfil.html", {
        "request": request, "user": user, "avatars": AVATARS,
    })


@router.post("/perfil")
def save_profile(request: Request, avatar: str = Form(...), user=Depends(require_login)):
    if is_valid(avatar):
        conn = get_db()
        conn.execute("UPDATE users SET avatar=? WHERE id=?", (avatar, user["id"]))
        conn.commit()
        conn.close()
    return RedirectResponse("/perfil", status_code=303)
