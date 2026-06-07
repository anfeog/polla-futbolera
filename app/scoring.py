"""
Sistema de puntuación:
  - Resultado exacto:                        +3 pts
  - Aciertas ganador/empate (no marcador):   +1 pt
  - Aciertas jugador en la posición correcta
    de su equipo (ej: 1er gol Colombia):     +2 pts
  - Aciertas que ese gol fue autogol:        +10 pts
  - Cada premio del Mundial acertado
    (Bota/Balón/Guante de Oro):              +10 pts

Regla anti-exploit: los slots de goleadores son EXACTAMENTE iguales
al marcador predicho. Si dices 2-1, tienes 2 slots para el local y 1
para el visitante — no más. Predecir 99-98 obliga a acertar 197 goles
en orden correcto, lo que es imposible en la práctica.
"""
from app.database import get_db

POINTS_EXACT = 3
POINTS_WINNER = 1
POINTS_SCORER = 2
POINTS_OWN_GOAL = 20
POINTS_AWARD = 10
POINTS_ADVANCES = 1   # aciertas quién pasa en penales
POINTS_PENALTY = 2    # aciertas el marcador exacto de penales

KO_STAGES = {"Last 32", "Last 16", "Quarter Finals", "Semi Finals", "Third Place", "Final"}


def _goals_by_team_ordered(match_goals: list, team: str) -> list:
    """Devuelve los goles reales de un equipo ordenados por minuto."""
    goals = [g for g in match_goals if g["team"] == team]
    return sorted(goals, key=lambda g: (g["minute"] or 999))


def calculate_match_points(prediction_id: int) -> float:
    conn = get_db()

    pred = conn.execute(
        "SELECT * FROM predictions WHERE id = ?", (prediction_id,)
    ).fetchone()

    match = conn.execute(
        "SELECT * FROM matches WHERE id = ?", (pred["match_id"],)
    ).fetchone()

    if match["home_score"] is None or match["away_score"] is None:
        conn.close()
        return 0.0

    points = 0.0
    hit_exact = 0
    hit_winner = 0
    scorers_hit = 0
    ph, pa = pred["home_score_pred"], pred["away_score_pred"]
    rh, ra = match["home_score"], match["away_score"]

    # Puntos por resultado
    if ph == rh and pa == ra:
        points += POINTS_EXACT
        hit_exact = 1
    elif (ph > pa and rh > ra) or (ph < pa and rh < ra) or (ph == pa and rh == ra):
        points += POINTS_WINNER
        hit_winner = 1

    # Puntos por goleadores ordenados
    real_goals = conn.execute(
        "SELECT * FROM match_goals WHERE match_id = ?", (match["id"],)
    ).fetchall()

    scorer_preds = conn.execute(
        "SELECT * FROM goalscorer_predictions WHERE prediction_id = ? ORDER BY team, position",
        (prediction_id,)
    ).fetchall()

    for team in [match["home_team"], match["away_team"]]:
        actual = _goals_by_team_ordered(real_goals, team)
        predicted = [p for p in scorer_preds if p["team"] == team]

        for gp in predicted:
            pos = gp["position"] - 1  # convertir a índice 0
            if pos >= len(actual):
                continue

            actual_goal = actual[pos]

            if gp["is_own_goal"]:
                if actual_goal["is_own_goal"]:
                    points += POINTS_OWN_GOAL
                    scorers_hit += 1
            else:
                if (not actual_goal["is_own_goal"]
                        and gp["player_name"]
                        and gp["player_name"].strip().lower() == (actual_goal["player_name"] or "").strip().lower()):
                    points += POINTS_SCORER
                    scorers_hit += 1

    # Puntos por penales (solo fase eliminatoria con empate en 90 min)
    advances_hit = 0
    penalty_score_hit = 0
    if match["stage"] in KO_STAGES and match["advances_team"]:
        # +1 si acertaste quién avanza
        if pred["advances_team"] and pred["advances_team"] == match["advances_team"]:
            points += POINTS_ADVANCES
            advances_hit = 1
        # +2 si acertaste el marcador exacto de penales
        if (pred["penalty_home"] is not None and pred["penalty_away"] is not None
                and match["penalty_home"] is not None and match["penalty_away"] is not None
                and pred["penalty_home"] == match["penalty_home"]
                and pred["penalty_away"] == match["penalty_away"]):
            points += POINTS_PENALTY
            penalty_score_hit = 1

    conn.execute(
        """UPDATE predictions
           SET points=?, hit_exact=?, hit_winner=?, scorers_hit=?,
               advances_hit=?, penalty_score_hit=?
           WHERE id=?""",
        (points, hit_exact, hit_winner, scorers_hit,
         advances_hit, penalty_score_hit, prediction_id)
    )
    conn.commit()
    conn.close()
    return points


def _norm(s) -> str:
    return (s or "").strip().lower()


def award_points_for_user(user_id: int, conn=None) -> int:
    """+10 por cada premio del Mundial acertado (Bota/Balón/Guante de Oro)."""
    own = conn is None
    if own:
        conn = get_db()
    real = conn.execute("SELECT * FROM tournament_awards WHERE id = 1").fetchone()
    pred = conn.execute(
        "SELECT * FROM award_predictions WHERE user_id = ?", (user_id,)
    ).fetchone()
    pts = 0
    if real and pred:
        for field in ("top_scorer", "best_player", "best_keeper"):
            if real[field] and _norm(pred[field]) == _norm(real[field]):
                pts += POINTS_AWARD
    if own:
        conn.close()
    return pts


def recalculate_all_for_match(match_id: int):
    conn = get_db()
    preds = conn.execute(
        "SELECT id FROM predictions WHERE match_id = ?", (match_id,)
    ).fetchall()
    conn.close()
    for p in preds:
        calculate_match_points(p["id"])
