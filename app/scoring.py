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
POINTS_SOLO = 3       # eres el ÚNICO que clava el marcador exacto de un partido
POINTS_TOTAL_EXACT = 20   # clavas el total de goles del Mundial
POINTS_TOTAL_CLOSE = 5    # nadie lo clava: el más cercano se lleva esto

# Puntos por cada pregunta bonus (la "verdad" la fija el admin)
AWARD_POINTS = {
    "top_scorer":      10,   # Bota de Oro
    "best_player":     10,   # Balón de Oro
    "best_keeper":     10,   # Guante de Oro
    "champion":        15,   # Campeón del Mundial
    "runner_up":       10,   # Subcampeón
    "final_penalties":  5,   # ¿La final se decide por penales? (si/no)
}

KO_STAGES = {"Last 32", "Last 16", "Quarter Finals", "Semi Finals", "Third Place", "Final"}


def _goals_by_team_ordered(match_goals: list, team: str) -> list:
    """Devuelve los goles reales de un equipo ordenados por minuto."""
    goals = [g for g in match_goals if g["team"] == team]
    return sorted(goals, key=lambda g: (g["minute"] or 999))


def _norm_player(s) -> str:
    """Normaliza nombre de jugador para comparar (sin acentos, minúsculas)."""
    import unicodedata
    s = (s or "").strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower()


def _goalscorer_points(scorer_preds, real_goals, home_team, away_team):
    """
    Puntos de goleador: +2 por jugador en su posición correcta dentro de su
    equipo, +20 por autogol acertado. El orden es por minuto, que es estable
    (el gol #1 ya marcado sigue siendo el #1), así sirve igual para el cálculo
    final y para los puntos provisionales en vivo.
    Devuelve (puntos, aciertos).
    """
    points = 0.0
    hits = 0
    for team in (home_team, away_team):
        actual = _goals_by_team_ordered(real_goals, team)
        predicted = [p for p in scorer_preds if p["team"] == team]
        for gp in predicted:
            pos = gp["position"] - 1
            if pos >= len(actual):
                continue
            actual_goal = actual[pos]
            if gp["is_own_goal"]:
                if actual_goal["is_own_goal"]:
                    points += POINTS_OWN_GOAL
                    hits += 1
            elif (not actual_goal["is_own_goal"]
                    and gp["player_name"]
                    and _norm_player(gp["player_name"]) == _norm_player(actual_goal["player_name"])):
                points += POINTS_SCORER
                hits += 1
    return points, hits


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

    sc_pts, scorers_hit = _goalscorer_points(
        scorer_preds, real_goals, match["home_team"], match["away_team"]
    )
    points += sc_pts

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
    """Puntos por cada pregunta bonus acertada (premios + campeón/subcampeón/final)."""
    own = conn is None
    if own:
        conn = get_db()
    real = conn.execute("SELECT * FROM tournament_awards WHERE id = 1").fetchone()
    pred = conn.execute(
        "SELECT * FROM award_predictions WHERE user_id = ?", (user_id,)
    ).fetchone()
    pts = 0
    if real and pred:
        for field, value in AWARD_POINTS.items():
            # La columna puede no existir en filas antiguas: usar get con default
            rv = real[field] if field in real.keys() else None
            pv = pred[field] if field in pred.keys() else None
            if rv and _norm(pv) == _norm(rv):
                pts += value
    if own:
        conn.close()
    return pts


def tournament_finished(conn) -> bool:
    """True si la Final ya se jugó (el torneo terminó)."""
    row = conn.execute(
        "SELECT COUNT(*) c FROM matches WHERE stage='Final' AND status='FINISHED'"
    ).fetchone()
    return (row["c"] or 0) > 0


def real_total_goals(conn) -> int:
    """Suma de todos los goles de partidos ya finalizados."""
    row = conn.execute(
        "SELECT COALESCE(SUM(home_score + away_score), 0) g "
        "FROM matches WHERE status='FINISHED' AND home_score IS NOT NULL"
    ).fetchone()
    return int(row["g"] or 0)


def total_goals_bonus(conn) -> dict:
    """
    Bonus por predecir el total de goles del Mundial.
    Solo se reparte cuando el torneo terminó (Final jugada).
    Devuelve {user_id: puntos}: +20 a quien lo clave; si nadie acierta,
    +5 a el/los más cercano(s).
    """
    if not tournament_finished(conn):
        return {}
    real = real_total_goals(conn)
    preds = conn.execute("""
        SELECT ap.user_id, ap.total_goals
        FROM award_predictions ap
        JOIN users u ON u.id = ap.user_id
        WHERE u.is_admin = 0 AND ap.total_goals IS NOT NULL
    """).fetchall()
    if not preds:
        return {}

    out = {}
    exact = [p for p in preds if p["total_goals"] == real]
    if exact:
        for p in exact:
            out[p["user_id"]] = POINTS_TOTAL_EXACT
    else:
        best = min(abs(p["total_goals"] - real) for p in preds)
        for p in preds:
            if abs(p["total_goals"] - real) == best:
                out[p["user_id"]] = POINTS_TOTAL_CLOSE
    return out


def live_provisional_points(conn) -> dict:
    """
    Puntos provisionales (marcador/ganador + goleadores) por partidos EN CURSO.
    No toca la BD — solo calcula en memoria para mostrar en /ranking.
    El orden de goleadores es por minuto, estable, así que los goles ya
    marcados cuentan provisionalmente y solo pueden sumar a medida que avanza.

    Devuelve {user_id: {"result": x, "scorers": y, "joker": z, "total": t}}
    con el desglose de dónde vienen los puntos provisionales.
    """
    live = conn.execute(
        "SELECT id, home_team, away_team, home_score, away_score FROM matches "
        "WHERE status IN ('IN_PLAY','PAUSED') AND home_score IS NOT NULL"
    ).fetchall()

    if not live:
        return {}

    result: dict = {}

    def _bucket(uid):
        return result.setdefault(uid, {"result": 0.0, "scorers": 0.0, "joker": 0.0, "total": 0.0})

    for m in live:
        rh, ra = m["home_score"], m["away_score"]
        ht, at = m["home_team"], m["away_team"]

        real_goals = conn.execute(
            "SELECT * FROM match_goals WHERE match_id = ?", (m["id"],)
        ).fetchall()
        preds = conn.execute(
            "SELECT id, user_id, home_score_pred, away_score_pred, is_joker, points "
            "FROM predictions WHERE match_id = ?", (m["id"],)
        ).fetchall()

        # Goleadores predichos de todos, agrupados por predicción (1 sola consulta)
        scorer_rows = conn.execute("""
            SELECT gp.prediction_id, gp.team, gp.position, gp.player_name, gp.is_own_goal
            FROM goalscorer_predictions gp
            JOIN predictions p ON p.id = gp.prediction_id
            WHERE p.match_id = ?
        """, (m["id"],)).fetchall()
        scorers_by_pred: dict = {}
        for sr in scorer_rows:
            scorers_by_pred.setdefault(sr["prediction_id"], []).append(sr)

        for p in preds:
            # Si el partido ya tiene puntos calculados, no añadir provisional
            if (p["points"] or 0) != 0:
                continue

            ph, pa = p["home_score_pred"], p["away_score_pred"]
            result_pts = 0.0
            if ph == rh and pa == ra:
                result_pts = POINTS_EXACT
            elif (ph > pa and rh > ra) or (ph < pa and rh < ra) or (ph == pa and rh == ra):
                result_pts = POINTS_WINNER

            # Goleadores ya marcados que caen en su posición correcta
            scorer_pts, _ = _goalscorer_points(
                scorers_by_pred.get(p["id"], []), real_goals, ht, at
            )

            base = result_pts + scorer_pts
            if base <= 0:
                continue

            # Comodín x2: duplica todos los puntos del partido
            joker_extra = base if p["is_joker"] else 0.0

            b = _bucket(p["user_id"])
            b["result"]  += result_pts
            b["scorers"] += scorer_pts
            b["joker"]   += joker_extra
            b["total"]   += base + joker_extra

    return result


def recalculate_all_for_match(match_id: int):
    conn = get_db()
    preds = conn.execute(
        "SELECT id FROM predictions WHERE match_id = ?", (match_id,)
    ).fetchall()
    conn.close()
    for p in preds:
        calculate_match_points(p["id"])
    _mark_solo_hits(match_id)


def _mark_solo_hits(match_id: int):
    """Marca solo_hit=1 si EXACTAMENTE un usuario clavó el marcador del partido."""
    conn = get_db()
    exact = conn.execute(
        "SELECT id FROM predictions WHERE match_id = ? AND hit_exact = 1",
        (match_id,)
    ).fetchall()
    # Reiniciar todos a 0 y marcar solo si hay un único acierto exacto
    conn.execute("UPDATE predictions SET solo_hit = 0 WHERE match_id = ?", (match_id,))
    if len(exact) == 1:
        conn.execute("UPDATE predictions SET solo_hit = 1 WHERE id = ?", (exact[0]["id"],))
    conn.commit()
    conn.close()
