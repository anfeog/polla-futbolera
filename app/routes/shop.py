"""Tienda de comodines: gasta puntos para comprar un comodín x2 o supercomodín x3."""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.auth import require_login
from app.templating import templates
from app.timeutils import is_locked
from app.scoring import BOOST_PRICES, user_balance

router = APIRouter()

BOOST_LABELS = {2: "Comodín x2", 3: "Supercomodín x3"}


def _active_boost(conn, user_id):
    """Comodín comprado que está EQUIPADO en un partido aún abierto (o None).
    Si su partido ya cerró, queda 'gastado' y no cuenta como activo."""
    rows = conn.execute("""
        SELECT p.boost, p.match_id, m.kickoff, m.home_team, m.away_team
        FROM predictions p JOIN matches m ON m.id = p.match_id
        WHERE p.user_id = ? AND p.boost > 0
    """, (user_id,)).fetchall()
    for r in rows:
        if not is_locked(r["kickoff"]):
            return r
    return None


@router.get("/tienda", response_class=HTMLResponse)
def tienda(request: Request, user=Depends(require_login), ok: str = "", err: str = ""):
    conn = get_db()
    balance = user_balance(conn, user["id"])
    owned = conn.execute(
        "SELECT COALESCE(boost_owned, 0) b FROM users WHERE id = ?", (user["id"],)
    ).fetchone()["b"]
    active = _active_boost(conn, user["id"])
    conn.close()
    return templates.TemplateResponse("tienda.html", {
        "request": request, "user": user,
        "balance": balance, "owned": owned, "active": active,
        "prices": BOOST_PRICES, "labels": BOOST_LABELS,
        "ok": ok, "err": err,
    })


@router.post("/tienda/comprar")
def comprar(request: Request, tipo: int = Form(...), user=Depends(require_login)):
    conn = get_db()
    if tipo not in BOOST_PRICES:
        conn.close()
        return RedirectResponse("/tienda", status_code=303)
    owned = conn.execute(
        "SELECT COALESCE(boost_owned, 0) b FROM users WHERE id = ?", (user["id"],)
    ).fetchone()["b"]
    active = _active_boost(conn, user["id"])
    balance = user_balance(conn, user["id"])
    price = BOOST_PRICES[tipo]
    # Solo uno a la vez: no comprar si ya tienes uno sin usar o equipado sin jugar.
    if owned or active:
        conn.close()
        return RedirectResponse("/tienda?err=uno", status_code=303)
    if balance < price:
        conn.close()
        return RedirectResponse("/tienda?err=saldo", status_code=303)
    conn.execute(
        "UPDATE users SET boost_owned = ?, points_spent = COALESCE(points_spent, 0) + ? WHERE id = ?",
        (tipo, price, user["id"]),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/tienda?ok=1", status_code=303)
