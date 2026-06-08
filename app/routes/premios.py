from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.auth import require_login
from app.templating import templates
from app.timeutils import is_past
from app.scoring import tournament_finished, real_total_goals

router = APIRouter()


def _first_kickoff(conn) -> str | None:
    row = conn.execute(
        "SELECT MIN(kickoff) k FROM matches WHERE home_team != 'Por definir'"
    ).fetchone()
    return row["k"] if row else None


@router.get("/premios", response_class=HTMLResponse)
def awards_form(request: Request, user=Depends(require_login)):
    conn = get_db()
    pred = conn.execute(
        "SELECT * FROM award_predictions WHERE user_id = ?", (user["id"],)
    ).fetchone()
    real = conn.execute("SELECT * FROM tournament_awards WHERE id = 1").fetchone()
    locked = is_past(_first_kickoff(conn))
    # Listas para autocompletar (todos los jugadores / solo arqueros)
    all_players = [r["name"] for r in conn.execute(
        "SELECT DISTINCT name FROM players ORDER BY name"
    ).fetchall()]
    keepers = [r["name"] for r in conn.execute(
        "SELECT DISTINCT name FROM players WHERE position='Goalkeeper' ORDER BY name"
    ).fetchall()]
    teams = [r["t"] for r in conn.execute("""
        SELECT DISTINCT home_team AS t FROM matches WHERE home_team != 'Por definir'
        UNION SELECT DISTINCT away_team AS t FROM matches WHERE away_team != 'Por definir'
        ORDER BY t
    """).fetchall()]
    # Total de goles real: solo se muestra cuando el Mundial terminó
    real_total = real_total_goals(conn) if tournament_finished(conn) else None
    conn.close()
    return templates.TemplateResponse("premios.html", {
        "request": request, "user": user,
        "pred": pred, "real": real, "locked": locked,
        "all_players": all_players, "keepers": keepers, "teams": teams,
        "real_total": real_total,
    })


@router.post("/premios")
def save_awards(
    request: Request,
    top_scorer: str = Form(""),
    best_player: str = Form(""),
    best_keeper: str = Form(""),
    champion: str = Form(""),
    runner_up: str = Form(""),
    final_penalties: str = Form(""),
    total_goals: str = Form(""),
    user=Depends(require_login),
):
    conn = get_db()
    if is_past(_first_kickoff(conn)):
        conn.close()
        return RedirectResponse("/premios", status_code=303)

    try:
        tg = int(total_goals) if total_goals.strip() else None
        if tg is not None and tg < 0:
            tg = None
    except ValueError:
        tg = None

    conn.execute("""
        INSERT INTO award_predictions
            (user_id, top_scorer, best_player, best_keeper, champion, runner_up, final_penalties, total_goals)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            top_scorer=excluded.top_scorer,
            best_player=excluded.best_player,
            best_keeper=excluded.best_keeper,
            champion=excluded.champion,
            runner_up=excluded.runner_up,
            final_penalties=excluded.final_penalties,
            total_goals=excluded.total_goals
    """, (user["id"], top_scorer.strip(), best_player.strip(), best_keeper.strip(),
          champion.strip(), runner_up.strip(), final_penalties.strip(), tg))
    conn.commit()
    conn.close()
    return RedirectResponse("/premios", status_code=303)
