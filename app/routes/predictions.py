from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.auth import require_login
from app.templating import templates
from app.timeutils import is_locked
from app.football_api import get_squad

router = APIRouter()


@router.get("/prediccion/{match_id}", response_class=HTMLResponse)
def prediction_form(match_id: int, request: Request, user=Depends(require_login)):
    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        raise HTTPException(404, "Partido no encontrado")

    # Bloquear si faltan menos de 1 hora para el inicio
    if is_locked(match["kickoff"]):
        conn.close()
        return RedirectResponse("/partidos")

    existing = conn.execute(
        "SELECT * FROM predictions WHERE user_id = ? AND match_id = ?",
        (user["id"], match_id)
    ).fetchone()

    existing_scorers = []
    if existing:
        existing_scorers = conn.execute(
            "SELECT * FROM goalscorer_predictions WHERE prediction_id = ?",
            (existing["id"],)
        ).fetchall()

    # Predicciones de los otros usuarios para este partido
    others = conn.execute("""
        SELECT u.username, u.avatar,
               p.id as pred_id, p.home_score_pred, p.away_score_pred,
               p.advances_team, p.penalty_home, p.penalty_away
        FROM predictions p
        JOIN users u ON u.id = p.user_id
        WHERE p.match_id = ? AND p.user_id != ?
        ORDER BY u.username
    """, (match_id, user["id"])).fetchall()

    others_scorers = {}
    for pred in others:
        scorers = conn.execute("""
            SELECT team, position, player_name, is_own_goal
            FROM goalscorer_predictions
            WHERE prediction_id = ?
            ORDER BY position
        """, (pred["pred_id"],)).fetchall()
        others_scorers[pred["pred_id"]] = scorers

    conn.close()

    # Plantillas para los desplegables (solo nombres)
    home_squad = [p["name"] for p in get_squad(match["home_team_api_id"])]
    away_squad = [p["name"] for p in get_squad(match["away_team_api_id"])]

    KO_STAGES = {"Last 32", "Last 16", "Quarter Finals", "Semi Finals", "Third Place", "Final"}
    return templates.TemplateResponse("prediction_form.html", {
        "request": request,
        "user": user,
        "match": match,
        "existing": existing,
        "existing_scorers": existing_scorers,
        "home_squad": home_squad,
        "away_squad": away_squad,
        "is_knockout": match["stage"] in KO_STAGES,
        "others": others,
        "others_scorers": others_scorers,
    })


@router.post("/prediccion/{match_id}")
async def save_prediction(match_id: int, request: Request, user=Depends(require_login)):
    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        raise HTTPException(404, "Partido no encontrado")

    if is_locked(match["kickoff"]):
        conn.close()
        raise HTTPException(400, "Los pronósticos cerraron (1 hora antes del partido)")

    KO_STAGES = {"Last 32", "Last 16", "Quarter Finals", "Semi Finals", "Third Place", "Final"}

    form = await request.form()
    home_pred = int(form.get("home_score", 0))
    away_pred = int(form.get("away_score", 0))

    # Penales: solo fase KO y empate
    is_ko = match["stage"] in KO_STAGES
    if is_ko and home_pred == away_pred:
        advances_team = (form.get("advances_team") or "").strip() or None
        try:
            penalty_home = int(form.get("penalty_home") or 0)
            penalty_away = int(form.get("penalty_away") or 0)
        except (ValueError, TypeError):
            penalty_home = penalty_away = None
        # Validar que penales no empatan entre sí
        if penalty_home is not None and penalty_home == penalty_away:
            penalty_home = penalty_away = None
    else:
        advances_team = penalty_home = penalty_away = None

    # Upsert predicción
    existing = conn.execute(
        "SELECT id FROM predictions WHERE user_id = ? AND match_id = ?",
        (user["id"], match_id)
    ).fetchone()

    if existing:
        pred_id = existing["id"]
        conn.execute(
            """UPDATE predictions
               SET home_score_pred=?, away_score_pred=?,
                   advances_team=?, penalty_home=?, penalty_away=?
               WHERE id=?""",
            (home_pred, away_pred, advances_team, penalty_home, penalty_away, pred_id)
        )
        conn.execute("DELETE FROM goalscorer_predictions WHERE prediction_id=?", (pred_id,))
    else:
        cur = conn.execute(
            """INSERT INTO predictions
               (user_id, match_id, home_score_pred, away_score_pred,
                advances_team, penalty_home, penalty_away)
               VALUES (?,?,?,?,?,?,?)""",
            (user["id"], match_id, home_pred, away_pred,
             advances_team, penalty_home, penalty_away)
        )
        pred_id = cur.lastrowid

    # Guardar goleadores: un slot por gol, identificados por team + position
    for team_key, total_goals in [("home", home_pred), ("away", away_pred)]:
        team_name = match["home_team"] if team_key == "home" else match["away_team"]
        for pos in range(1, total_goals + 1):
            field = f"scorer_{team_key}_{pos}"
            player = (form.get(field, "") or "").strip()
            is_own = 1 if form.get(f"{field}_own") else 0
            conn.execute(
                "INSERT INTO goalscorer_predictions (prediction_id, team, position, player_name, is_own_goal) VALUES (?,?,?,?,?)",
                (pred_id, team_name, pos, player or None, is_own)
            )

    conn.commit()
    conn.close()
    return RedirectResponse("/partidos", status_code=303)
