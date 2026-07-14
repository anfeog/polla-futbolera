from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.auth import require_login
from app.templating import templates
from app.timeutils import is_locked
from app.football_api import get_squad
from app.scoring import effective_multiplier, POINTS_SOLO

router = APIRouter()


def _ordered_real_goals(conn, match_id, team):
    """Goles reales de un equipo ordenados por minuto (posición estable)."""
    rows = conn.execute(
        "SELECT player_name, is_own_goal FROM match_goals WHERE match_id=? AND team=? ORDER BY minute",
        (match_id, team)
    ).fetchall()
    return rows


@router.get("/prediccion/{match_id}", response_class=HTMLResponse)
def prediction_form(match_id: int, request: Request, user=Depends(require_login)):
    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        raise HTTPException(404, "Partido no encontrado")

    # Cerrado (a <1h del inicio o ya jugado): vista de SOLO LECTURA
    if is_locked(match["kickoff"]):
        return _prediction_readonly(conn, match, match_id, user, request)

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

    # Los pronósticos de los demás NO se muestran mientras el partido sigue
    # abierto (anti-copia). Se ven en la vista de solo lectura, tras el cierre.

    # Comodín: ¿ya tiene uno en otro partido de esta fase?
    joker_other = conn.execute("""
        SELECT m.home_team, m.away_team, m.kickoff
        FROM predictions p JOIN matches m ON m.id = p.match_id
        WHERE p.user_id = ? AND p.is_joker = 1 AND m.stage = ? AND m.id != ?
        LIMIT 1
    """, (user["id"], match["stage"], match_id)).fetchone()
    # Si ese partido ya cerró, el comodín está GASTADO en esta fase: no se mueve.
    joker_locked = bool(joker_other and is_locked(joker_other["kickoff"]))

    # Tienda: comodín comprado en inventario y el que esté puesto en ESTE partido.
    boost_owned = conn.execute(
        "SELECT COALESCE(boost_owned, 0) b FROM users WHERE id = ?", (user["id"],)
    ).fetchone()["b"]
    boost_current = existing["boost"] if existing else 0

    # Excepción pública: el pronóstico de Andrés en Argentina vs Suiza se
    # muestra a TODOS, aunque el partido siga abierto (fuera de la regla
    # anti-copia normal). Solo el de él — nadie más se ve antes del cierre.
    # Se arma igual que la tarjeta de "todos" en la vista post-cierre.
    andres_preview = None
    if {match["home_team"], match["away_team"]} == {"Argentina", "Switzerland"}:
        r = conn.execute("""
            SELECT p.id, p.home_score_pred, p.away_score_pred, p.is_joker, p.advances_team, u.avatar
            FROM predictions p JOIN users u ON u.id = p.user_id
            WHERE u.username = 'Andres' AND p.match_id = ?
        """, (match_id,)).fetchone()
        if r:
            andres_preview = {
                "username": "Andrés", "avatar": r["avatar"] or "⚽",
                "home": r["home_score_pred"], "away": r["away_score_pred"],
                "advances": r["advances_team"], "is_joker": r["is_joker"],
                "scorers": _scorer_lines_for(conn, match, match_id, r["id"], False, {}),
            }

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
        "is_joker": bool(existing and existing["is_joker"]),
        "joker_other": joker_other,
        "joker_locked": joker_locked,
        "boost_owned": boost_owned,
        "boost_current": boost_current,
        "andres_preview": andres_preview,
    })


def _scorer_lines_for(conn, match, match_id, pred_id, finished, real_cache):
    """Lista de goleadores predichos por equipo, con acierto si ya se jugó."""
    lines = {"home": [], "away": []}
    for side, team in (("home", match["home_team"]), ("away", match["away_team"])):
        predicted = conn.execute(
            "SELECT position, player_name, is_own_goal FROM goalscorer_predictions "
            "WHERE prediction_id=? AND team=? ORDER BY position",
            (pred_id, team)
        ).fetchall()
        if team not in real_cache:
            real_cache[team] = _ordered_real_goals(conn, match_id, team) if finished else []
        real = real_cache[team]
        for gp in predicted:
            pos = gp["position"]
            real_goal = real[pos - 1] if pos - 1 < len(real) else None
            if gp["is_own_goal"]:
                pred_label = "⚽ Autogol"
                hit = bool(real_goal and real_goal["is_own_goal"])
            else:
                pred_label = gp["player_name"] or "—"
                hit = bool(real_goal and not real_goal["is_own_goal"]
                           and gp["player_name"]
                           and gp["player_name"].strip().lower() == (real_goal["player_name"] or "").strip().lower())
            real_label = None
            if finished and real_goal:
                real_label = "⚽ Autogol" if real_goal["is_own_goal"] else (real_goal["player_name"] or "—")
            lines[side].append({
                "pos": pos, "predicted": pred_label,
                "real": real_label, "hit": hit if finished else None,
            })
    return lines


def _result_status(pred, finished):
    if not (finished and pred):
        return None
    if pred["hit_exact"]:
        return "exact"
    if pred["hit_winner"]:
        return "winner"
    return "miss"


def _prediction_readonly(conn, match, match_id, user, request):
    """Vista de solo lectura: tu pronóstico + el de todos, con aciertos si ya se jugó."""
    finished = match["status"] == "FINISHED"
    live = match["status"] in ("IN_PLAY", "PAUSED")
    real_cache = {}

    pred = conn.execute(
        "SELECT * FROM predictions WHERE user_id=? AND match_id=?",
        (user["id"], match_id)
    ).fetchone()

    scorer_lines = {"home": [], "away": []}
    if pred:
        scorer_lines = _scorer_lines_for(conn, match, match_id, pred["id"], finished, real_cache)
    result_status = _result_status(pred, finished)

    # Pronósticos de TODOS los participantes (transparencia)
    all_rows = conn.execute("""
        SELECT p.id, p.user_id, p.home_score_pred, p.away_score_pred,
               p.is_joker, p.boost, p.points, p.hit_exact, p.hit_winner, p.advances_team,
               p.solo_hit, p.solo_advance,
               u.username, u.avatar
        FROM predictions p
        JOIN users u ON u.id = p.user_id
        WHERE p.match_id = ? AND u.is_admin = 0
    """, (match_id,)).fetchall()

    everyone = []
    for r in all_rows:
        base = r["points"] or 0
        mult = effective_multiplier(r["is_joker"], r["boost"])
        solo_bonus = ((r["solo_hit"] or 0) + (r["solo_advance"] or 0)) * POINTS_SOLO * mult
        everyone.append({
            "username": r["username"], "avatar": r["avatar"] or "⚽",
            "is_me": r["user_id"] == user["id"],
            "home": r["home_score_pred"], "away": r["away_score_pred"],
            "advances": r["advances_team"],
            "is_joker": r["is_joker"],
            "points": base,
            "total_points": base * mult + solo_bonus,
            "solo_bonus": solo_bonus,
            "result_status": _result_status(r, finished),
            "scorers": _scorer_lines_for(conn, match, match_id, r["id"], finished, real_cache),
        })
    # Ordenar: si ya se jugó, por puntos desc; si no, alfabético
    if finished:
        everyone.sort(key=lambda e: (-e["total_points"], e["username"].lower()))
    else:
        everyone.sort(key=lambda e: e["username"].lower())

    # Goleadores reales (para mostrar quién marcó de verdad)
    real_scorers = {"home": [], "away": []}
    if finished:
        for side, team in (("home", match["home_team"]), ("away", match["away_team"])):
            gs = real_cache.get(team) or _ordered_real_goals(conn, match_id, team)
            real_scorers[side] = [
                ("⚽ Autogol" if g["is_own_goal"] else (g["player_name"] or "—")) for g in gs
            ]

    conn.close()
    return templates.TemplateResponse("prediction_view.html", {
        "request": request, "user": user, "match": match,
        "pred": pred, "finished": finished, "live": live,
        "scorer_lines": scorer_lines, "result_status": result_status,
        "everyone": everyone, "real_scorers": real_scorers,
    })


@router.post("/prediccion/{match_id}")
async def save_prediction(match_id: int, request: Request, user=Depends(require_login)):
    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        raise HTTPException(404, "Partido no encontrado")

    if is_locked(match["kickoff"]):
        conn.close()
        raise HTTPException(400, "Los pronósticos ya cerraron para este partido")

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

    # Comodín (x2): solo uno por fase. Se puede mover entre partidos ABIERTOS,
    # pero si el comodín ya está en un partido de esta fase que YA CERRÓ, quedó
    # gastado y no se puede mover ni reactivar en otro (anti-exploit: re-apuntar
    # el comodín con resultados ya conocidos).
    want_joker = 1 if form.get("use_joker") else 0
    spent_rows = conn.execute("""
        SELECT m.kickoff FROM predictions p JOIN matches m ON m.id = p.match_id
        WHERE p.user_id = ? AND p.is_joker = 1 AND m.stage = ? AND m.id != ?
    """, (user["id"], match["stage"], match_id)).fetchall()
    joker_spent = any(is_locked(r["kickoff"]) for r in spent_rows)

    if want_joker and not joker_spent:
        # Mover: quitarlo de los demás partidos de la fase (todos abiertos) y ponerlo aquí.
        conn.execute("""
            UPDATE predictions SET is_joker = 0
            WHERE user_id = ? AND match_id IN (SELECT id FROM matches WHERE stage = ?)
        """, (user["id"], match["stage"]))
        conn.execute("UPDATE predictions SET is_joker = 1 WHERE id = ?", (pred_id,))
    else:
        # No lo quiere, o ya está gastado en un partido cerrado de esta fase.
        conn.execute("UPDATE predictions SET is_joker = 0 WHERE id = ?", (pred_id,))

    # ── Comodín COMPRADO (tienda): equipar/quitar el que tiene en inventario ──
    # No se cobra aquí (se pagó al comprar). Equipar consume el de inventario;
    # quitarlo (en un partido aún abierto) lo devuelve al inventario para moverlo.
    want_boost = 1 if form.get("use_boost") else 0
    urow = conn.execute("SELECT COALESCE(boost_owned, 0) b FROM users WHERE id = ?", (user["id"],)).fetchone()
    boost_owned = urow["b"]
    cur_boost = conn.execute("SELECT boost FROM predictions WHERE id = ?", (pred_id,)).fetchone()["boost"] or 0
    if want_boost and not cur_boost and boost_owned:
        # Equipar el comprado aquí: sale del inventario.
        conn.execute("UPDATE predictions SET boost = ? WHERE id = ?", (boost_owned, pred_id))
        conn.execute("UPDATE users SET boost_owned = 0 WHERE id = ?", (user["id"],))
    elif not want_boost and cur_boost:
        # Quitarlo: vuelve al inventario (para moverlo a otro partido abierto).
        conn.execute("UPDATE predictions SET boost = 0 WHERE id = ?", (pred_id,))
        conn.execute("UPDATE users SET boost_owned = ? WHERE id = ?", (cur_boost, user["id"]))

    conn.commit()
    conn.close()
    return RedirectResponse("/partidos", status_code=303)
