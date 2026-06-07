from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.auth import verify_password, create_session_token, get_current_user
from app.templating import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/partidos")
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()

    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Usuario o contraseña incorrectos"}
        )

    token = create_session_token(user["id"])
    # Primera vez que entra: mostrar tutorial
    dest = "/como-jugar" if not user["tutorial_seen"] else "/partidos"
    response = RedirectResponse(dest, status_code=303)
    response.set_cookie("session", token, httponly=True, max_age=60 * 60 * 24 * 7)
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("session")
    return response
