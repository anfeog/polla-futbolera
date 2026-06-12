from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.auth import require_login
from app.templating import templates
from app.scoring import award_points_for_user, total_goals_bonus, live_provisional_points, POINTS_SOLO
from app.i18n import t

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


def _chart_context() -> dict:
    """Calcula todos los datos para las 4 gráficas. Reutilizable en /ranking."""
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

    # ── 2) Barras apiladas: desglose de puntos por origen (top 5) ──────────────
    conn2 = get_db()
    agg = conn2.execute("""
        SELECT u.id, u.username, u.avatar,
               COALESCE(SUM(p.points), 0)            AS pts,
               COALESCE(SUM(p.points * p.is_joker), 0) AS joker_bonus,
               COALESCE(SUM(p.solo_hit), 0)          AS solo_hits,
               COALESCE(SUM(p.hit_exact), 0)         AS ex,
               COALESCE(SUM(p.hit_winner), 0)        AS wi,
               COALESCE(SUM(p.advances_hit), 0)      AS adv,
               COALESCE(SUM(p.penalty_score_hit), 0) AS pen,
               SUM(CASE WHEN m.status='FINISHED' THEN 1 ELSE 0 END) AS played
        FROM users u
        LEFT JOIN predictions p ON p.user_id = u.id
        LEFT JOIN matches m     ON m.id = p.match_id
        WHERE u.is_admin = 0
        GROUP BY u.id
    """).fetchall()

    tg_bonus = total_goals_bonus(conn2)   # total de goles (al terminar el Mundial)

    breakdown = []
    for r in agg:
        exacto  = (r["ex"] or 0) * 3
        ganador = (r["wi"] or 0) * 1
        penales = (r["adv"] or 0) * 1 + (r["pen"] or 0) * 2
        award   = award_points_for_user(r["id"], conn2) + tg_bonus.get(r["id"], 0)
        comodin = r["joker_bonus"] or 0
        solo    = (r["solo_hits"] or 0) * POINTS_SOLO
        # Lo que queda son goleadores/autogoles
        goleador = max(0, (r["pts"] or 0) - exacto - ganador - penales)
        total = (r["pts"] or 0) + comodin + solo + award
        breakdown.append({
            "username": r["username"], "avatar": r["avatar"] or "⚽",
            "exacto": exacto, "ganador": ganador, "goleador": round(goleador, 1),
            "penales": penales, "premios": award, "comodin": comodin, "solo": solo,
            "exact_count": r["ex"] or 0,
            "total": total, "played": r["played"] or 0,
        })
    conn2.close()

    top5 = sorted(breakdown, key=lambda b: -b["total"])[:5]
    bar_labels = [b["username"] for b in top5]
    bar_segments = [
        {"label": t("Marcador exacto"), "color": "#22c55e", "data": [b["exacto"]   for b in top5]},
        {"label": t("Ganador"),         "color": "#3b82f6", "data": [b["ganador"]  for b in top5]},
        {"label": t("Goleadores"),      "color": "#f59e0b", "data": [b["goleador"] for b in top5]},
        {"label": t("Penales"),         "color": "#a855f7", "data": [b["penales"]  for b in top5]},
        {"label": t("Comodín x2"),      "color": "#06b6d4", "data": [b["comodin"]  for b in top5]},
        {"label": t("Solo tú"),         "color": "#facc15", "data": [b["solo"]     for b in top5]},
        {"label": t("Premios"),         "color": "#ec4899", "data": [b["premios"]  for b in top5]},
    ]
    has_bars = any(b["total"] > 0 for b in top5)

    # ── 3) "Bola de cristal rota" 🔮💥 — los peores prediciendo (humor) ─────────
    played_users = [b for b in breakdown if b["played"] > 0]
    for b in played_users:
        hits_pts = b["exacto"] + b["ganador"]   # aprox de aciertos de resultado
        b["pct"] = round((b["total"] / (b["played"] * 3)) * 100)  # % sobre el máximo posible por marcador
    worst = sorted(played_users, key=lambda b: (b["total"], -b["played"]))[:5]
    worst_labels  = [b["username"] for b in worst]
    worst_avatars = [b["avatar"] for b in worst]
    worst_pct     = [b["pct"] for b in worst]
    worst_pts     = [b["total"] for b in worst]
    has_worst = len(worst) > 0

    # ── 4) Francotiradores 🎯 — marcadores exactos ────────────────────────────
    sharp = sorted(played_users,
                   key=lambda b: (-b["exact_count"],
                                  -(b["exact_count"] / b["played"] if b["played"] else 0)))[:5]
    sharp_labels  = [b["username"] for b in sharp]
    sharp_avatars = [b["avatar"] for b in sharp]
    sharp_counts  = [b["exact_count"] for b in sharp]
    sharp_pct     = [round(b["exact_count"] / b["played"] * 100) if b["played"] else 0 for b in sharp]
    has_sharp = any(b["exact_count"] > 0 for b in sharp)

    return {
        "labels": labels, "datasets": datasets,
        "has_data": bool(days),
        "bar_labels": bar_labels, "bar_segments": bar_segments, "has_bars": has_bars,
        "worst_labels": worst_labels, "worst_avatars": worst_avatars,
        "worst_pct": worst_pct, "worst_pts": worst_pts, "has_worst": has_worst,
        "sharp_labels": sharp_labels, "sharp_avatars": sharp_avatars,
        "sharp_counts": sharp_counts, "sharp_pct": sharp_pct, "has_sharp": has_sharp,
    }


@router.get("/graficas", response_class=HTMLResponse)
def graficas(request: Request, user=Depends(require_login)):
    return templates.TemplateResponse("graficas.html", {
        "request": request, "user": user, **_chart_context(),
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

    # Todos los agregados se cuentan SOLO sobre partidos FINISHED, para que
    # sean consistentes con `played`. Los partidos en vivo (IN_PLAY) suman
    # aparte vía live_provisional_points. Así el % nunca pasa de 100.
    rows = conn.execute("""
        SELECT u.id, u.username, u.avatar, u.status_msg,
               COALESCE(SUM(CASE WHEN m.status='FINISHED' THEN p.points ELSE 0 END), 0)            AS match_points,
               COALESCE(SUM(CASE WHEN m.status='FINISHED' THEN p.points * p.is_joker ELSE 0 END), 0) AS joker_bonus,
               COALESCE(SUM(CASE WHEN m.status='FINISHED' THEN p.solo_hit ELSE 0 END), 0)          AS solo_hits,
               COALESCE(SUM(CASE WHEN m.status='FINISHED' THEN p.hit_exact ELSE 0 END), 0)         AS exact_hits,
               COALESCE(SUM(CASE WHEN m.status='FINISHED' THEN p.hit_winner ELSE 0 END), 0)        AS winner_hits,
               COALESCE(SUM(CASE WHEN m.status='FINISHED' THEN p.scorers_hit ELSE 0 END), 0)       AS scorers_hit,
               SUM(CASE WHEN m.status='FINISHED' THEN 1 ELSE 0 END) AS played
        FROM users u
        LEFT JOIN predictions p ON p.user_id = u.id
        LEFT JOIN matches m ON m.id = p.match_id
        WHERE u.is_admin = 0
        GROUP BY u.id
    """).fetchall()

    tg_bonus   = total_goals_bonus(conn)
    live_bonus = live_provisional_points(conn)   # {user_id: {result, scorers, joker, total}}

    ranking = []
    for r in rows:
        award_pts = award_points_for_user(r["id"], conn) + tg_bonus.get(r["id"], 0)
        played = r["played"] or 0
        results_hit = r["exact_hits"] + r["winner_hits"]
        pct = min(round(results_hit / played * 100), 100) if played else 0
        solo_pts = (r["solo_hits"] or 0) * POINTS_SOLO
        joker_bonus = r["joker_bonus"] or 0
        total = r["match_points"] + joker_bonus + solo_pts + award_pts
        live = live_bonus.get(r["id"]) or {}
        ranking.append({
            "id": r["id"],
            "username": r["username"],
            "avatar": r["avatar"] or "⚽",
            "status_msg": r["status_msg"],
            "total_points": total,
            "provisional":      round(live.get("total", 0), 1),   # extra si el marcador actual es el final
            "prov_result":      round(live.get("result", 0), 1),
            "prov_scorers":     round(live.get("scorers", 0), 1),
            "prov_joker":       round(live.get("joker", 0), 1),
            "award_points": award_pts,
            "joker_bonus": joker_bonus,
            "solo_hits": r["solo_hits"] or 0,
            "exact_hits": r["exact_hits"],
            "winner_hits": r["winner_hits"],
            "scorers_hit": r["scorers_hit"],
            "played": played,
            "pct": pct,
        })

    any_live = bool(live_bonus)
    ranking.sort(key=lambda x: (-(x["total_points"] + x["provisional"]), -x["exact_hits"]))

    # IDs del podio (top 3): solo ellos pueden poner viñeta
    podium_ids = [row["id"] for row in ranking[:3]]

    conn.close()
    return templates.TemplateResponse("ranking.html", {
        "request": request, "user": user, "ranking": ranking,
        "podium_ids": podium_ids,
        "any_live": any_live,
        **_chart_context(),
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
