from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
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
        SELECT u.id, u.username, u.avatar,
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
            "username": r["username"],
            "avatar": r["avatar"] or "⚽",
            "total_points": r["match_points"] + award_pts,
            "award_points": award_pts,
            "exact_hits": r["exact_hits"],
            "winner_hits": r["winner_hits"],
            "scorers_hit": r["scorers_hit"],
            "played": played,
            "pct": pct,
        })

    ranking.sort(key=lambda x: (-x["total_points"], -x["exact_hits"]))

    conn.close()
    return templates.TemplateResponse("ranking.html", {
        "request": request, "user": user, "ranking": ranking,
    })
