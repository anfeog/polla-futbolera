from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.auth import require_login, verify_password, hash_password
from app.templating import templates
from app.avatars import AVATARS, is_valid

router = APIRouter()

_PW_MESSAGES = {
    "ok":       ("✅ Contraseña actualizada correctamente.", "ok"),
    "wrong":    ("La contraseña actual no es correcta.", "err"),
    "short":    ("La nueva contraseña debe tener al menos 4 caracteres.", "err"),
    "mismatch": ("Las dos contraseñas nuevas no coinciden.", "err"),
}


@router.get("/perfil", response_class=HTMLResponse)
def profile(request: Request, user=Depends(require_login), pw: str = ""):
    return templates.TemplateResponse("perfil.html", {
        "request": request, "user": user, "avatars": AVATARS,
        "pw_msg": _PW_MESSAGES.get(pw),
    })


@router.post("/perfil")
def save_profile(request: Request, avatar: str = Form(...), user=Depends(require_login)):
    if is_valid(avatar):
        conn = get_db()
        conn.execute("UPDATE users SET avatar=? WHERE id=?", (avatar, user["id"]))
        conn.commit()
        conn.close()
    return RedirectResponse("/perfil", status_code=303)


@router.post("/perfil/clave")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user=Depends(require_login),
):
    conn = get_db()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE id=?", (user["id"],)
    ).fetchone()

    if not row or not verify_password(current_password, row["password_hash"]):
        conn.close()
        return RedirectResponse("/perfil?pw=wrong", status_code=303)
    if len(new_password) < 4:
        conn.close()
        return RedirectResponse("/perfil?pw=short", status_code=303)
    if new_password != confirm_password:
        conn.close()
        return RedirectResponse("/perfil?pw=mismatch", status_code=303)

    conn.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (hash_password(new_password), user["id"])
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/perfil?pw=ok", status_code=303)
