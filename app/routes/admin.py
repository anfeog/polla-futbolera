from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.auth import require_admin, hash_password
from app.football_api import fetch_and_store_matches, fetch_and_store_squads
from app.templating import templates
from app.scoring import recalculate_all_for_match, KO_STAGES
import asyncio

router = APIRouter(prefix="/admin")


@router.get("", response_class=HTMLResponse)
def admin_panel(request: Request, user=Depends(require_admin)):
    from datetime import datetime, timezone
    conn = get_db()
    users = conn.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id").fetchall()
    awards = conn.execute("SELECT * FROM tournament_awards WHERE id=1").fetchone()
    n_players = conn.execute("SELECT COUNT(*) c FROM players").fetchone()["c"]
    n_matches = conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]
    conn.close()
    return templates.TemplateResponse("admin.html", {
        "request": request, "user": user, "users": users, "awards": awards,
        "n_players": n_players, "n_matches": n_matches,
        "now_hhmmss": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
    })


@router.post("/crear-usuario")
def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user=Depends(require_admin)
):
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        users = conn.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id").fetchall()
        conn.close()
        return templates.TemplateResponse("admin.html", {
            "request": request, "user": user, "users": users,
            "error": f"El usuario '{username}' ya existe"
        })
    hashed = hash_password(password)
    conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, hashed))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin", status_code=303)


@router.post("/eliminar-usuario/{user_id}")
def delete_user(user_id: int, user=Depends(require_admin)):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ? AND is_admin = 0", (user_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin", status_code=303)


@router.post("/premios-ganadores")
def set_award_winners(
    request: Request,
    top_scorer: str = Form(""),
    best_player: str = Form(""),
    best_keeper: str = Form(""),
    champion: str = Form(""),
    runner_up: str = Form(""),
    final_penalties: str = Form(""),
    user=Depends(require_admin),
):
    conn = get_db()
    conn.execute("""
        UPDATE tournament_awards
        SET top_scorer=?, best_player=?, best_keeper=?,
            champion=?, runner_up=?, final_penalties=?
        WHERE id=1
    """, (top_scorer.strip(), best_player.strip(), best_keeper.strip(),
          champion.strip(), runner_up.strip(), final_penalties.strip()))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin", status_code=303)


@router.post("/cargar-plantillas")
async def load_squads(background_tasks: BackgroundTasks, user=Depends(require_admin)):
    """Lanza la carga de plantillas en background y retorna inmediatamente."""
    async def _run():
        try:
            await fetch_and_store_squads()
        except Exception as e:
            print(f"[squads] Error: {e}")
    background_tasks.add_task(_run)
    return RedirectResponse("/admin?squads=loading", status_code=303)


@router.get("/resultados", response_class=HTMLResponse)
def admin_resultados(request: Request, user=Depends(require_admin), stage: str = ""):
    conn = get_db()
    stages = [r["stage"] for r in conn.execute(
        "SELECT DISTINCT stage FROM matches ORDER BY CASE stage "
        "WHEN 'Group Stage' THEN 1 WHEN 'Last 32' THEN 2 WHEN 'Last 16' THEN 3 "
        "WHEN 'Quarter Finals' THEN 4 WHEN 'Semi Finals' THEN 5 "
        "WHEN 'Third Place' THEN 6 WHEN 'Final' THEN 7 ELSE 99 END"
    ).fetchall()]
    active_stage = stage or (stages[0] if stages else "")
    matches = conn.execute(
        "SELECT * FROM matches WHERE stage=? ORDER BY kickoff", (active_stage,)
    ).fetchall()
    conn.close()
    return templates.TemplateResponse("admin_resultados.html", {
        "request": request, "user": user,
        "stages": stages, "active_stage": active_stage,
        "matches": matches, "ko_stages": KO_STAGES,
        "ok": request.query_params.get("ok"),
    })


@router.post("/resultado/{match_id}")
async def set_match_result(
    match_id: int,
    request: Request,
    user=Depends(require_admin),
):
    form = await request.form()
    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not match:
        conn.close()
        return RedirectResponse("/admin/resultados", status_code=303)

    home_team = (form.get("home_team") or match["home_team"]).strip()
    away_team = (form.get("away_team") or match["away_team"]).strip()

    home_s = form.get("home_score", "")
    away_s = form.get("away_score", "")
    if home_s == "" or away_s == "":
        # Limpiar resultado
        conn.execute(
            "UPDATE matches SET home_team=?, away_team=?, home_score=NULL, away_score=NULL, "
            "penalty_home=NULL, penalty_away=NULL, advances_team=NULL, status='TIMED' WHERE id=?",
            (home_team, away_team, match_id)
        )
    else:
        home_score = int(home_s)
        away_score = int(away_s)
        pen_h = form.get("penalty_home", "")
        pen_a = form.get("penalty_away", "")
        penalty_home = int(pen_h) if pen_h != "" else None
        penalty_away = int(pen_a) if pen_a != "" else None

        if penalty_home is not None and penalty_away is not None:
            advances = home_team if penalty_home > penalty_away else away_team
        elif home_score != away_score:
            advances = home_team if home_score > away_score else away_team
        else:
            advances = None

        conn.execute(
            """UPDATE matches SET
               home_team=?, away_team=?,
               home_score=?, away_score=?, status='FINISHED',
               penalty_home=?, penalty_away=?, advances_team=?
               WHERE id=?""",
            (home_team, away_team, home_score, away_score,
             penalty_home, penalty_away, advances, match_id)
        )

    conn.commit()
    conn.close()
    recalculate_all_for_match(match_id)

    stage_slug = form.get("stage", "")
    return RedirectResponse(f"/admin/resultados?stage={stage_slug}&ok={match_id}", status_code=303)


@router.post("/cargar-partidos")
async def load_matches(request: Request, user=Depends(require_admin)):
    try:
        count = await fetch_and_store_matches()
        return RedirectResponse(f"/admin?imported={count}", status_code=303)
    except Exception as e:
        conn = get_db()
        users = conn.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id").fetchall()
        conn.close()
        return templates.TemplateResponse("admin.html", {
            "request": request, "user": user, "users": users,
            "error": f"Error al importar partidos: {e}"
        })


@router.post("/actualizar-resultados")
async def force_update_results(user=Depends(require_admin)):
    """Fuerza una actualización inmediata de resultados (no espera los 5 min del scheduler)."""
    from app.football_api import update_finished_matches
    try:
        recalced = await update_finished_matches()
    except Exception as e:
        return RedirectResponse(f"/admin?force_error={e}", status_code=303)
    conn = get_db()
    live = conn.execute(
        "SELECT COUNT(*) c FROM matches WHERE status IN ('IN_PLAY','PAUSED')"
    ).fetchone()["c"]
    conn.close()
    return RedirectResponse(f"/admin?updated={recalced}&live={live}", status_code=303)
