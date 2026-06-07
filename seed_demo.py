"""
Genera datos de DEMOSTRACIÓN para ver el ranking funcionando.
Crea jugadores ficticios, pronósticos y simula resultados de los primeros partidos.

  python seed_demo.py          -> recrea DB, importa partidos y siembra demo
  python seed_demo.py --wipe   -> borra solo los datos demo (deja admin y partidos)

NO usar en producción con datos reales.
"""
import sys
import random
import asyncio
from dotenv import load_dotenv
load_dotenv()

from app.database import get_db, init_db
from app.auth import hash_password
from app.scoring import recalculate_all_for_match

DEMO_USERS = ["Lucho", "Cris", "Dani", "Mafe", "Pipe"]


def wipe_demo():
    conn = get_db()
    qmarks = ",".join("?" * len(DEMO_USERS))
    conn.execute(f"DELETE FROM users WHERE username IN ({qmarks})", DEMO_USERS)
    conn.execute("DELETE FROM match_goals")
    conn.execute("UPDATE matches SET home_score=NULL, away_score=NULL, status='TIMED'")
    conn.commit()
    conn.close()
    print("Datos demo borrados.")


def seed():
    random.seed(42)
    conn = get_db()

    # Crear usuarios demo
    for name in DEMO_USERS:
        if not conn.execute("SELECT 1 FROM users WHERE username=?", (name,)).fetchone():
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (name, hash_password("demo1234"))
            )
    conn.commit()
    users = conn.execute("SELECT id, username FROM users WHERE is_admin=0").fetchall()

    # Tomar los primeros 6 partidos y simular resultados
    matches = conn.execute(
        "SELECT * FROM matches WHERE home_team != 'Por definir' ORDER BY kickoff ASC LIMIT 6"
    ).fetchall()

    finished_ids = []
    for m in matches:
        rh, ra = random.randint(0, 3), random.randint(0, 3)
        conn.execute(
            "UPDATE matches SET home_score=?, away_score=?, status='FINISHED' WHERE id=?",
            (rh, ra, m["id"])
        )
        conn.execute("DELETE FROM match_goals WHERE match_id=?", (m["id"],))
        # Goleadores reales ficticios
        for i in range(rh):
            conn.execute(
                "INSERT INTO match_goals (match_id, player_name, team, minute, is_own_goal) VALUES (?,?,?,?,0)",
                (m["id"], f"{m['home_tla']} Jugador {i+1}", m["home_team"], (i + 1) * 15)
            )
        for i in range(ra):
            conn.execute(
                "INSERT INTO match_goals (match_id, player_name, team, minute, is_own_goal) VALUES (?,?,?,?,0)",
                (m["id"], f"{m['away_tla']} Jugador {i+1}", m["away_team"], (i + 1) * 18)
            )
        finished_ids.append((m["id"], m, rh, ra))

    # Cada usuario pronostica con distinto acierto
    for u in users:
        for (mid, m, rh, ra) in finished_ids:
            # A veces clava el marcador, a veces se acerca, a veces falla
            roll = random.random()
            if roll < 0.3:
                ph, pa = rh, ra                      # exacto
            elif roll < 0.65:
                ph, pa = rh, max(0, ra + random.choice([-1, 1]))  # ganador quizá
            else:
                ph, pa = random.randint(0, 3), random.randint(0, 3)  # azar

            cur = conn.execute(
                "INSERT OR REPLACE INTO predictions (user_id, match_id, home_score_pred, away_score_pred) VALUES (?,?,?,?)",
                (u["id"], mid, ph, pa)
            )
            pred_id = cur.lastrowid

            # Goleadores: acierta el real ~50% de las veces
            for i in range(ph):
                guess = f"{m['home_tla']} Jugador {i+1}" if random.random() < 0.5 else "Random FC"
                conn.execute(
                    "INSERT INTO goalscorer_predictions (prediction_id, team, position, player_name, is_own_goal) VALUES (?,?,?,?,0)",
                    (pred_id, m["home_team"], i + 1, guess)
                )
            for i in range(pa):
                guess = f"{m['away_tla']} Jugador {i+1}" if random.random() < 0.5 else "Random FC"
                conn.execute(
                    "INSERT INTO goalscorer_predictions (prediction_id, team, position, player_name, is_own_goal) VALUES (?,?,?,?,0)",
                    (pred_id, m["away_team"], i + 1, guess)
                )

    conn.commit()
    conn.close()

    for (mid, *_rest) in finished_ids:
        recalculate_all_for_match(mid)

    print(f"Demo lista: {len(DEMO_USERS)} jugadores, {len(finished_ids)} partidos simulados.")


if __name__ == "__main__":
    if "--wipe" in sys.argv:
        wipe_demo()
    else:
        init_db()
        seed()
