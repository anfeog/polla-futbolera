from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.auth import require_login
from app.templating import templates
from app.scoring import award_points_for_user

router = APIRouter()


@router.get("/goleadores", response_class=HTMLResponse)
def goleadores(request: Request, user=Depends(require_login)):
    conn = get_db()

    # Top 10 goleadores (no autogoles): desempate por menos partidos jugados
    scorers = conn.execute("""
        SELECT
            mg.player_name,
            mg.team,
            COUNT(*)                   AS goals,
            COUNT(DISTINCT mg.match_id) AS pj,
            (SELECT CASE WHEN m2.home_team = mg.team
                         THEN m2.home_flag ELSE m2.away_flag END
             FROM matches m2 WHERE m2.id = mg.match_id LIMIT 1) AS flag,
            (SELECT CASE WHEN m2.home_team = mg.team
                         THEN m2.home_tla ELSE m2.away_tla END
             FROM matches m2 WHERE m2.id = mg.match_id LIMIT 1) AS tla
        FROM match_goals mg
        WHERE mg.is_own_goal = 0
          AND mg.player_name IS NOT NULL
          AND mg.player_name != ''
        GROUP BY mg.player_name, mg.team
        ORDER BY goals DESC, pj ASC
        LIMIT 10
    """).fetchall()

    # Autogoles como dato curioso
    own_goals = conn.execute("""
        SELECT
            mg.player_name,
            mg.team,
            COUNT(*) AS own_goals,
            (SELECT CASE WHEN m2.home_team = mg.team
                         THEN m2.home_flag ELSE m2.away_flag END
             FROM matches m2 WHERE m2.id = mg.match_id LIMIT 1) AS flag,
            (SELECT CASE WHEN m2.home_team = mg.team
                         THEN m2.home_tla ELSE m2.away_tla END
             FROM matches m2 WHERE m2.id = mg.match_id LIMIT 1) AS tla
        FROM match_goals mg
        WHERE mg.is_own_goal = 1
          AND mg.player_name IS NOT NULL
          AND mg.player_name != ''
        GROUP BY mg.player_name, mg.team
        ORDER BY own_goals DESC
        LIMIT 5
    """).fetchall()

    # Total de goles anotados en el torneo
    total_goals = conn.execute(
        "SELECT COUNT(*) c FROM match_goals WHERE is_own_goal = 0"
    ).fetchone()["c"]

    total_matches_played = conn.execute(
        "SELECT COUNT(*) c FROM matches WHERE status = 'FINISHED'"
    ).fetchone()["c"]

    conn.close()

    return templates.TemplateResponse("goleadores.html", {
        "request": request, "user": user,
        "scorers": [dict(r) for r in scorers],
        "own_goals": [dict(r) for r in own_goals],
        "total_goals": total_goals,
        "total_matches": total_matches_played,
    })


@router.get("/graficas", response_class=HTMLResponse)
def graficas(request: Request, user=Depends(require_login)):
    conn = get_db()

    # Puntos por usuario y día (de partidos ya finalizados)
    rows = conn.execute("""
        SELECT u.id, u.username, u.avatar,
               substr(m.kickoff, 1, 10) AS day,
               SUM(p.points)            AS pts
        FROM users u
        JOIN predictions p ON p.user_id = u.id
        JOIN matches m     ON m.id = p.match_id
        WHERE u.is_admin = 0 AND m.status = 'FINISHED'
        GROUP BY u.id, day
    """).fetchall()

    users = conn.execute(
        "SELECT id, username, avatar FROM users WHERE is_admin = 0 ORDER BY username"
    ).fetchall()
    conn.close()

    # Días distintos con partidos jugados, ordenados
    days = sorted({r["day"] for r in rows})
    pts_map = {(r["id"], r["day"]): (r["pts"] or 0) for r in rows}

    # Etiquetas de eje X: '2026-06-11' → '11 Jun'
    MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
              "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    def fmt_day(d):
        try:
            y, m, dd = d.split("-")
            return f"{int(dd)} {MONTHS[int(m) - 1]}"
        except Exception:
            return d
    labels = [fmt_day(d) for d in days]

    # Paleta de colores fija por jugador
    PALETTE = ["#22c55e", "#ef4444", "#3b82f6", "#f59e0b", "#a855f7",
               "#ec4899", "#14b8a6", "#eab308", "#8b5cf6", "#06b6d4",
               "#f97316", "#84cc16", "#e11d48", "#0ea5e9", "#d946ef"]

    datasets = []
    for i, u in enumerate(users):
        cum = 0.0
        data = []
        for d in days:
            cum += pts_map.get((u["id"], d), 0) or 0
            data.append(round(cum, 1))
        datasets.append({
            "label": u["username"],
            "avatar": u["avatar"] or "⚽",
            "data": data,
            "color": PALETTE[i % len(PALETTE)],
            "total": data[-1] if data else 0,
        })

    # Ordenar leyenda por total de puntos (desc)
    datasets.sort(key=lambda d: -d["total"])

    return templates.TemplateResponse("graficas.html", {
        "request": request, "user": user,
        "labels": labels, "datasets": datasets,
        "has_data": bool(days),
    })


@router.get("/como-jugar", response_class=HTMLResponse)
def como_jugar(request: Request, user=Depends(require_login)):
    conn = get_db()
    conn.execute("UPDATE users SET tutorial_seen=1 WHERE id=?", (user["id"],))
    conn.commit()
    conn.close()
    return templates.TemplateResponse("como_jugar.html", {
        "request": request, "user": user,
    })


@router.get("/ranking", response_class=HTMLResponse)
def ranking(request: Request, user=Depends(require_login)):
    conn = get_db()

    rows = conn.execute("""
        SELECT u.id, u.username, u.avatar, u.status_msg,
               COALESCE(SUM(p.points), 0)        AS match_points,
               COALESCE(SUM(p.hit_exact), 0)     AS exact_hits,
               COALESCE(SUM(p.hit_winner), 0)    AS winner_hits,
               COALESCE(SUM(p.scorers_hit), 0)   AS scorers_hit,
               SUM(CASE WHEN m.status='FINISHED' THEN 1 ELSE 0 END) AS played
        FROM users u
        LEFT JOIN predictions p ON p.user_id = u.id
        LEFT JOIN matches m ON m.id = p.match_id
        WHERE u.is_admin = 0
        GROUP BY u.id
    """).fetchall()

    ranking = []
    for r in rows:
        award_pts = award_points_for_user(r["id"], conn)
        played = r["played"] or 0
        results_hit = r["exact_hits"] + r["winner_hits"]
        pct = round(results_hit / played * 100) if played else 0
        ranking.append({
            "id": r["id"],
            "username": r["username"],
            "avatar": r["avatar"] or "⚽",
            "status_msg": r["status_msg"],
            "total_points": r["match_points"] + award_pts,
            "award_points": award_pts,
            "exact_hits": r["exact_hits"],
            "winner_hits": r["winner_hits"],
            "scorers_hit": r["scorers_hit"],
            "played": played,
            "pct": pct,
        })

    ranking.sort(key=lambda x: (-x["total_points"], -x["exact_hits"]))

    # IDs del podio (top 3): solo ellos pueden poner viñeta
    podium_ids = [row["id"] for row in ranking[:3]]

    conn.close()
    return templates.TemplateResponse("ranking.html", {
        "request": request, "user": user, "ranking": ranking,
        "podium_ids": podium_ids,
    })


@router.post("/estado")
def set_estado(request: Request, msg: str = Form(""), user=Depends(require_login)):
    """Guarda la viñeta de cómic. Solo permitido si el usuario está en el podio."""
    conn = get_db()

    # Recalcular el ranking para validar que el usuario está en el top 3
    rows = conn.execute("""
        SELECT u.id, COALESCE(SUM(p.points), 0) AS match_points,
               COALESCE(SUM(p.hit_exact), 0)    AS exact_hits
        FROM users u
        LEFT JOIN predictions p ON p.user_id = u.id
        WHERE u.is_admin = 0
        GROUP BY u.id
    """).fetchall()
    standings = []
    for r in rows:
        standings.append((r["id"], r["match_points"] + award_points_for_user(r["id"], conn), r["exact_hits"]))
    standings.sort(key=lambda x: (-x[1], -x[2]))
    podium_ids = [s[0] for s in standings[:3]]

    if user["id"] in podium_ids:
        clean = (msg or "").strip()[:60] or None   # máx 60 caracteres
        conn.execute("UPDATE users SET status_msg=? WHERE id=?", (clean, user["id"]))
        conn.commit()

    conn.close()
    return RedirectResponse("/ranking", status_code=303)
