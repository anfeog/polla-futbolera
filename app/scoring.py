"""
Sistema de puntuación:
  - Resultado exacto:                        +3 pts
  - Aciertas ganador/empate (no marcador):   +1 pt
  - Aciertas jugador en la posición correcta
    de su equipo (ej: 1er gol Colombia):     +2 pts
  - Autogol, jugador y posición exactos:     +20 pts
  - Autogol, equipo correcto (no exacto):     +5 pts
  - Autogol, pero equipo contrario:           +2 pts
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
POINTS_OWN_GOAL_CLOSE = 5      # acertaste el EQUIPO del autogol, pero no la posición exacta
POINTS_OWN_GOAL_WRONG_SIDE = 2 # predijiste autogol y lo hubo, pero en el equipo contrario
POINTS_AWARD = 10
POINTS_ADVANCES = 1   # aciertas quién pasa en penales
POINTS_PENALTY = 2    # aciertas el marcador exacto de penales
POINTS_SOLO = 3       # eres el ÚNICO que clava el marcador exacto de un partido
POINTS_TOTAL_EXACT = 20   # clavas el total de goles del Mundial
POINTS_TOTAL_CLOSE = 5    # nadie lo clava: el más cercano se lleva esto
POINTS_FINAL_PARTICIPANT = 3   # el equipo que dijiste (campeón o subcampeón) SÍ jugó la Final,
                                # sin importar si acertaste cuál de los dos ganó

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

# ── Tienda de comodines ───────────────────────────────────────────────────────
BOOST_PRICES = {2: 2, 3: 5}   # x2 cuesta 2 pts, supercomodín x3 cuesta 5 pts


def effective_multiplier(is_joker, boost) -> int:
    """Multiplicador de un partido: el comprado manda; si no, el comodín gratis."""
    if boost and boost > 0:
        return boost
    return 2 if is_joker else 1


def user_earned_points(conn, user_id: int) -> float:
    """Puntos GANADOS (brutos, antes de descontar lo gastado en la tienda)."""
    row = conn.execute("""
        SELECT
          COALESCE(SUM(CASE WHEN m.status='FINISHED' THEN p.points ELSE 0 END), 0) AS match_points,
          COALESCE(SUM(CASE WHEN m.status='FINISHED' THEN p.points *
              ((CASE WHEN p.boost > 0 THEN p.boost WHEN p.is_joker THEN 2 ELSE 1 END) - 1)
            ELSE 0 END), 0) AS mult_bonus,
          COALESCE(SUM(CASE WHEN m.status='FINISHED' THEN p.solo_hit + p.solo_advance ELSE 0 END), 0) AS solo_hits
        FROM predictions p LEFT JOIN matches m ON m.id = p.match_id
        WHERE p.user_id = ?
    """, (user_id,)).fetchone()
    earned = (row["match_points"] or 0) + (row["mult_bonus"] or 0) + (row["solo_hits"] or 0) * POINTS_SOLO
    earned += award_points_for_user(user_id, conn)
    earned += total_goals_bonus(conn).get(user_id, 0)
    return earned


def user_balance(conn, user_id: int) -> float:
    """Saldo disponible para la tienda = ganados − gastados (= total en la tabla)."""
    spent = conn.execute(
        "SELECT COALESCE(points_spent, 0) s FROM users WHERE id = ?", (user_id,)
    ).fetchone()["s"]
    return user_earned_points(conn, user_id) - (spent or 0)


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


def _names_match(pred: str, real: str) -> bool:
    """
    Compara nombres de jugador de forma tolerante: las fuentes escriben distinto
    (ej. lista de plantilla 'Nestor Irankunda' vs ESPN 'Nestory Irankunda'). Se
    consideran iguales si: coinciden exactos, o comparten el apellido (último
    token, >=4 letras), o uno contiene al otro, o comparten algún token largo.
    """
    a, b = _norm_player(pred), _norm_player(real)
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = a.split(), b.split()
    if not ta or not tb:
        return False
    if ta[-1] == tb[-1] and len(ta[-1]) >= 4:      # mismo apellido
        return True
    if a in b or b in a:                            # uno contenido en el otro
        return True
    common = {t for t in ta if len(t) >= 4} & {t for t in tb if len(t) >= 4}
    return bool(common)


def _goalscorer_points(scorer_preds, real_goals, home_team, away_team):
    """
    Puntos de goleador: +2 por jugador en su posición correcta dentro de su
    equipo. Autogol en 3 niveles:
      +20  jugador exacto en la posición correcta
      +5   acertaste el EQUIPO del autogol, pero no la posición exacta
      +2   predijiste autogol y lo hubo, pero en el equipo contrario
    El orden es por minuto, que es estable (el gol #1 ya marcado sigue siendo
    el #1), así sirve igual para el cálculo final y para los puntos
    provisionales en vivo.
    Devuelve (puntos, aciertos).
    """
    points = 0.0
    hits = 0
    real_og_exists = any(g["is_own_goal"] for g in real_goals)
    og_predicted_any = False
    matched_og_side = False
    for team in (home_team, away_team):
        actual = _goals_by_team_ordered(real_goals, team)
        predicted = [p for p in scorer_preds if p["team"] == team]
        og_predicted = any(gp["is_own_goal"] for gp in predicted)
        if og_predicted:
            og_predicted_any = True
        og_actual    = any(g["is_own_goal"] for g in actual)
        og_exact     = False
        for gp in predicted:
            pos = gp["position"] - 1
            if pos >= len(actual):
                continue
            actual_goal = actual[pos]
            if gp["is_own_goal"]:
                if actual_goal["is_own_goal"]:
                    points += POINTS_OWN_GOAL
                    hits += 1
                    og_exact = True
            elif (not actual_goal["is_own_goal"]
                    and gp["player_name"]
                    and _names_match(gp["player_name"], actual_goal["player_name"])):
                points += POINTS_SCORER
                hits += 1
        # Consolación: predijiste autogol y hubo autogol del equipo, pero no en
        # la posición exacta (no obtuviste el +20). +5 una vez por equipo.
        if og_predicted and og_actual and not og_exact:
            points += POINTS_OWN_GOAL_CLOSE
            hits += 1
        if og_predicted and og_actual:
            matched_og_side = True
    # Consolación mínima: acertaste que habría autogol, pero se lo asignaste
    # al equipo contrario del que realmente lo sufrió/benefició.
    if og_predicted_any and real_og_exists and not matched_og_side:
        points += POINTS_OWN_GOAL_WRONG_SIDE
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

    # Puntos por "quién avanza" (fase eliminatoria): el ganador real es quien
    # avanza, ya sea por penales (match["advances_team"]) o por marcador limpio
    # en 90/120 min (sin penales). Así, si alguien predijo empate + señaló
    # quién pasaba y acertó al equipo que ganó, cuenta igual aunque el partido
    # NO haya llegado a penales.
    advances_hit = 0
    penalty_score_hit = 0
    real_advances = match["advances_team"]
    if not real_advances and match["stage"] in KO_STAGES:
        if rh > ra:
            real_advances = match["home_team"]
        elif ra > rh:
            real_advances = match["away_team"]
    if match["stage"] in KO_STAGES and real_advances:
        # Quién predijiste que avanza: si tu marcador YA es un ganador claro
        # (no empate), ese equipo es tu voto implícito — no hace falta el
        # selector de penales (ese solo aparece cuando predices empate).
        pred_advances = (pred["advances_team"] if ph == pa
                         else (match["home_team"] if ph > pa else match["away_team"]))
        # +1 si acertaste quién avanza. OJO: si predijiste un ganador directo
        # (no empate), acertar el ganador (+1 arriba) YA ES lo mismo que
        # acertar quién avanza — no se suma dos veces por la misma jugada.
        # El +1 aparte solo aplica cuando predijiste empate (adivinaste algo
        # extra: quién se lleva la tanda de penales).
        if pred_advances and pred_advances == real_advances:
            advances_hit = 1
            if ph == pa:
                points += POINTS_ADVANCES
        # +2 si acertaste el marcador exacto de penales (solo si de verdad hubo tanda)
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

        # Bono aparte: el equipo que dijiste como campeón y/o como subcampeón
        # realmente jugó la Final — no importa si acertaste cuál de los dos
        # ganó. +3 por cada uno (hasta +6 si adivinaste los dos finalistas).
        real_champion  = real["champion"] if "champion" in real.keys() else None
        real_runner_up = real["runner_up"] if "runner_up" in real.keys() else None
        real_finalists = {_norm(real_champion), _norm(real_runner_up)} - {""}
        if real_finalists:
            pred_champion  = pred["champion"] if "champion" in pred.keys() else None
            pred_runner_up = pred["runner_up"] if "runner_up" in pred.keys() else None
            for pv in (pred_champion, pred_runner_up):
                if pv and _norm(pv) in real_finalists:
                    pts += POINTS_FINAL_PARTICIPANT

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
    Se reparte cuando el torneo terminó (Final jugada), O ANTES si ya es
    matemáticamente imposible que alguien lo clave exacto (los goles solo
    suben — si el total real ya superó la apuesta más alta, nadie puede
    acertar y se define ya el/los más cercano(s)).
    Devuelve {user_id: puntos}: +20 a quien lo clave; si nadie puede
    acertar, +5 a el/los más cercano(s).
    """
    real = real_total_goals(conn)
    preds = conn.execute("""
        SELECT ap.user_id, ap.total_goals
        FROM award_predictions ap
        JOIN users u ON u.id = ap.user_id
        WHERE u.is_admin = 0 AND ap.total_goals IS NOT NULL
    """).fetchall()
    if not preds:
        return {}

    finished = tournament_finished(conn)
    exact_impossible = real > max(p["total_goals"] for p in preds)
    if not finished and not exact_impossible:
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
            "SELECT id, user_id, home_score_pred, away_score_pred, is_joker, boost, points "
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

            # Comodín (gratis x2 o comprado x2/x3): suma el extra del multiplicador
            joker_extra = base * (effective_multiplier(p["is_joker"], p["boost"]) - 1)

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
    _mark_solo_advance(match_id)


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


def _mark_solo_advance(match_id: int):
    """Marca solo_advance=1 si EXACTAMENTE un usuario acertó quién avanza (KO).
    Cuenta tanto a quien usó el selector de empate como a quien predijo un
    ganador directo (su marcador YA implica a quién elige). Es un bonus
    aparte del de marcador exacto (se pueden ganar los dos)."""
    conn = get_db()
    match = conn.execute(
        "SELECT stage, advances_team, home_team, away_team, home_score, away_score FROM matches WHERE id = ?",
        (match_id,)
    ).fetchone()
    conn.execute("UPDATE predictions SET solo_advance = 0 WHERE match_id = ?", (match_id,))
    real_advances = match["advances_team"] if match else None
    if match and not real_advances and match["stage"] in KO_STAGES:
        if match["home_score"] > match["away_score"]:
            real_advances = match["home_team"]
        elif match["away_score"] > match["home_score"]:
            real_advances = match["away_team"]
    if match and match["stage"] in KO_STAGES and real_advances:
        preds = conn.execute(
            "SELECT id, home_score_pred, away_score_pred, advances_team FROM predictions WHERE match_id = ?",
            (match_id,)
        ).fetchall()
        correct = []
        for p in preds:
            ph, pa = p["home_score_pred"], p["away_score_pred"]
            pred_advances = (p["advances_team"] if ph == pa
                             else (match["home_team"] if ph > pa else match["away_team"]))
            if pred_advances == real_advances:
                correct.append(p["id"])
        if len(correct) == 1:
            conn.execute("UPDATE predictions SET solo_advance = 1 WHERE id = ?", (correct[0],))
    conn.commit()
    conn.close()
