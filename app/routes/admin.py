from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.auth import require_admin, hash_password
from app.football_api import fetch_and_store_matches, fetch_and_store_squads
from app.templating import templates
from app.scoring import recalculate_all_for_match, KO_STAGES
import asyncio

router = APIRouter(prefix="/admin")

# Clave temporal que se asigna al resetear: el jugador entra con ella y la
# cambia en su perfil.
TEMP_PASSWORD = "soyhuevonsemeolvido"


def _render_admin(request, user, **extra):
    from datetime import datetime, timezone
    conn = get_db()
    users = conn.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id").fetchall()
    awards = conn.execute("SELECT * FROM tournament_awards WHERE id=1").fetchone()
    n_players = conn.execute("SELECT COUNT(*) c FROM players").fetchone()["c"]
    n_matches = conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]
    matches = conn.execute(
        "SELECT id, home_team, away_team, stage FROM matches "
        "WHERE home_team != 'Por definir' AND away_team != 'Por definir' ORDER BY kickoff"
    ).fetchall()
    banners = conn.execute("SELECT * FROM banners ORDER BY id DESC").fetchall()
    conn.close()
    ctx = {
        "request": request, "user": user, "users": users, "awards": awards,
        "n_players": n_players, "n_matches": n_matches, "matches": matches,
        "banners": banners,
        "now_hhmmss": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"),
    }
    ctx.update(extra)
    return templates.TemplateResponse("admin.html", ctx)


@router.get("", response_class=HTMLResponse)
def admin_panel(request: Request, user=Depends(require_admin), reset: str = "", joker: str = "", recalc: str = ""):
    extra = {}
    if reset:
        extra["reset_user"] = reset
        extra["reset_password"] = TEMP_PASSWORD
    if joker:
        extra["joker_msg"] = joker
    if recalc:
        extra["recalc_count"] = recalc
    return _render_admin(request, user, **extra)


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


@router.post("/resetear-clave/{user_id}")
def reset_password(user_id: int, user=Depends(require_admin)):
    """Asigna la clave temporal a un jugador que olvidó la suya."""
    conn = get_db()
    row = conn.execute(
        "SELECT username FROM users WHERE id = ? AND is_admin = 0", (user_id,)
    ).fetchone()
    if not row:
        conn.close()
        return RedirectResponse("/admin", status_code=303)
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(TEMP_PASSWORD), user_id),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(f"/admin?reset={row['username']}", status_code=303)


@router.post("/asignar-comodin")
def assign_joker(
    request: Request,
    user_id: int = Form(...),
    match_id: int = Form(...),
    user=Depends(require_admin),
):
    """(Re)asigna el comodín de un jugador a un partido, aunque ya esté cerrado.
    Útil para reparar comodines borrados por bugs. Respeta 'uno por fase'."""
    from urllib.parse import quote
    conn = get_db()
    match = conn.execute(
        "SELECT stage, home_team, away_team FROM matches WHERE id = ?", (match_id,)
    ).fetchone()
    urow = conn.execute(
        "SELECT username FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    pred = conn.execute(
        "SELECT id FROM predictions WHERE user_id = ? AND match_id = ?", (user_id, match_id)
    ).fetchone()
    if not match or not urow:
        conn.close()
        return RedirectResponse("/admin?joker=err_nodata", status_code=303)
    if not pred:
        # Sin predicción en ese partido no hay dónde poner el comodín.
        conn.close()
        return RedirectResponse("/admin?joker=err_nopred", status_code=303)
    # Uno por fase: quitar el comodín de los demás partidos de esa fase y ponerlo aquí.
    conn.execute(
        "UPDATE predictions SET is_joker = 0 WHERE user_id = ? "
        "AND match_id IN (SELECT id FROM matches WHERE stage = ?)",
        (user_id, match["stage"]),
    )
    conn.execute("UPDATE predictions SET is_joker = 1 WHERE id = ?", (pred["id"],))
    conn.commit()
    conn.close()
    label = f"{urow['username']} → {match['home_team']} vs {match['away_team']}"
    return RedirectResponse(f"/admin?joker=ok:{quote(label)}", status_code=303)


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

    # Goles ya registrados por partido (en orden), para precargar los inputs
    goals_by_match = {}
    for m in matches:
        gs = conn.execute(
            "SELECT player_name, team, is_own_goal FROM match_goals WHERE match_id=? ORDER BY minute",
            (m["id"],)
        ).fetchall()
        home_goals = [dict(g) for g in gs if g["team"] == m["home_team"]]
        away_goals = [dict(g) for g in gs if g["team"] == m["away_team"]]
        goals_by_match[m["id"]] = {"home": home_goals, "away": away_goals}

    all_players = [r["name"] for r in conn.execute(
        "SELECT DISTINCT name FROM players ORDER BY name"
    ).fetchall()]
    conn.close()
    return templates.TemplateResponse("admin_resultados.html", {
        "request": request, "user": user,
        "stages": stages, "active_stage": active_stage,
        "matches": matches, "ko_stages": KO_STAGES,
        "goals_by_match": goals_by_match, "all_players": all_players,
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

    # ¿En vivo (provisional) o final? Botón "live" deja status IN_PLAY sin calcular puntos.
    is_live = form.get("action") == "live"

    home_s = form.get("home_score", "")
    away_s = form.get("away_score", "")
    if home_s == "" or away_s == "":
        # Limpiar resultado y goles
        conn.execute(
            "UPDATE matches SET home_team=?, away_team=?, home_score=NULL, away_score=NULL, "
            "penalty_home=NULL, penalty_away=NULL, advances_team=NULL, status='TIMED' WHERE id=?",
            (home_team, away_team, match_id)
        )
        conn.execute("DELETE FROM match_goals WHERE match_id=?", (match_id,))
        # Resetear puntos de las predicciones de este partido
        conn.execute(
            "UPDATE predictions SET points=0, hit_exact=0, hit_winner=0, scorers_hit=0, "
            "solo_hit=0, advances_hit=0, penalty_score_hit=0 WHERE match_id=?",
            (match_id,)
        )
        conn.commit()
        conn.close()
        stage_slug = form.get("stage", "")
        return RedirectResponse(f"/admin/resultados?stage={stage_slug}&ok={match_id}", status_code=303)

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

    new_status = "IN_PLAY" if is_live else "FINISHED"
    conn.execute(
        """UPDATE matches SET
           home_team=?, away_team=?,
           home_score=?, away_score=?, status=?,
           penalty_home=?, penalty_away=?, advances_team=?
           WHERE id=?""",
        (home_team, away_team, home_score, away_score, new_status,
         penalty_home, penalty_away, advances, match_id)
    )

    # Goleadores en orden (slot i = i-ésimo gol del equipo). El minuto = posición
    # mantiene el orden estable para el cálculo de puntos.
    conn.execute("DELETE FROM match_goals WHERE match_id=?", (match_id,))
    for prefix, team, n in (("home", home_team, home_score), ("away", away_team, away_score)):
        for i in range(1, n + 1):
            name = (form.get(f"{prefix}_scorer_{i}") or "").strip()
            is_og = 1 if form.get(f"{prefix}_og_{i}") else 0
            if name or is_og:
                conn.execute(
                    "INSERT INTO match_goals (match_id, player_name, team, minute, is_own_goal) "
                    "VALUES (?,?,?,?,?)",
                    (match_id, name, team, i, is_og)
                )

    if is_live:
        # En vivo: dejar puntos en 0 para que el ranking los muestre como provisionales
        conn.execute(
            "UPDATE predictions SET points=0, hit_exact=0, hit_winner=0, scorers_hit=0, "
            "solo_hit=0, advances_hit=0, penalty_score_hit=0 WHERE match_id=?",
            (match_id,)
        )
        conn.commit()
        conn.close()
    else:
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


@router.post("/actualizar-resultados", response_class=HTMLResponse)
async def force_update_results(request: Request, user=Depends(require_admin)):
    """Fuerza la actualización inmediata y muestra el detalle de lo que ESPN devolvió."""
    from app.football_api import update_finished_matches
    from app.espn import sync_goalscorers
    import asyncio
    report = []
    try:
        recalced = await update_finished_matches()
        scorers = await asyncio.to_thread(sync_goalscorers, report)
    except Exception as e:
        return _render_admin(request, user, force_error=str(e))
    conn = get_db()
    live = conn.execute(
        "SELECT COUNT(*) c FROM matches WHERE status IN ('IN_PLAY','PAUSED')"
    ).fetchone()["c"]
    conn.close()
    return _render_admin(
        request, user,
        force_recalced=recalced, force_scorers=scorers,
        force_live=live, force_report=report,
    )


@router.post("/recalcular-todo")
def recalc_all(request: Request, user=Depends(require_admin)):
    """Recalcula los puntos de TODOS los partidos terminados. Úsalo cuando cambien
    las reglas de puntaje para aplicarlas retroactivamente (autogol +5, solo-avanza…)."""
    from app.scoring import recalculate_all_for_match
    conn = get_db()
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM matches WHERE status='FINISHED' AND home_score IS NOT NULL"
    ).fetchall()]
    conn.close()
    for mid in ids:
        recalculate_all_for_match(mid)
    return RedirectResponse(f"/admin?recalc={len(ids)}", status_code=303)


@router.post("/letreros/crear")
def create_banner(request: Request, text: str = Form(...), user=Depends(require_admin)):
    text = text.strip()
    if text:
        conn = get_db()
        conn.execute("INSERT INTO banners (text) VALUES (?)", (text,))
        conn.commit()
        conn.close()
    return RedirectResponse("/admin#letreros", status_code=303)


@router.post("/letreros/{banner_id}/toggle")
def toggle_banner(banner_id: int, user=Depends(require_admin)):
    conn = get_db()
    conn.execute("UPDATE banners SET active = 1 - active WHERE id = ?", (banner_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin#letreros", status_code=303)


@router.post("/letreros/{banner_id}/borrar")
def delete_banner(banner_id: int, user=Depends(require_admin)):
    conn = get_db()
    conn.execute("DELETE FROM banners WHERE id = ?", (banner_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin#letreros", status_code=303)
