"""
Seed de prueba: crea jeffsanti, dati, gogeta, salda248 y
simula predicciones + resultados para todos los partidos del 11 al 20 de junio.
Corre con:  python seed_usuarios.py
Limpia con: python seed_usuarios.py --wipe
"""
import sys, random
from dotenv import load_dotenv
load_dotenv()

from app.database import get_db, init_db
from app.auth import hash_password
from app.scoring import recalculate_all_for_match

USERS = [
    ("jeffsanti", "⚽", "demo1234"),
    ("dati",      "🦁", "demo1234"),
    ("gogeta",    "🔥", "demo1234"),
    ("salda248",  "👑", "demo1234"),
]

# Resultados inventados para dar variedad (home_score, away_score, goleadores)
# Si el equipo no tiene plantilla importada usamos nombres genéricos
MATCH_RESULTS = {}  # se genera dinámicamente abajo


def wipe():
    conn = get_db()
    for name, _, _ in USERS:
        conn.execute("DELETE FROM users WHERE username=?", (name,))
    conn.commit()
    conn.close()
    # Limpiar partidos simulados
    conn = get_db()
    conn.execute("UPDATE matches SET home_score=NULL, away_score=NULL, status='TIMED' WHERE kickoff>='2026-06-11' AND kickoff<='2026-06-20T23:59:00Z'")
    conn.execute("DELETE FROM match_goals WHERE match_id IN (SELECT id FROM matches WHERE kickoff>='2026-06-11' AND kickoff<='2026-06-20T23:59:00Z')")
    conn.execute("DELETE FROM predictions WHERE match_id IN (SELECT id FROM matches WHERE kickoff>='2026-06-11' AND kickoff<='2026-06-20T23:59:00Z')")
    conn.commit()
    conn.close()
    print("Limpiado.")


def get_squad_names(conn, team_api_id):
    if not team_api_id:
        return []
    rows = conn.execute("SELECT name FROM players WHERE team_api_id=? ORDER BY name", (team_api_id,)).fetchall()
    return [r["name"] for r in rows]


def seed():
    random.seed(99)
    init_db()
    conn = get_db()

    # 1. Crear usuarios
    for name, avatar, pwd in USERS:
        if not conn.execute("SELECT 1 FROM users WHERE username=?", (name,)).fetchone():
            conn.execute(
                "INSERT INTO users (username, password_hash, avatar) VALUES (?,?,?)",
                (name, hash_password(pwd), avatar)
            )
            print(f"  Usuario creado: {name}")
        else:
            # Actualizar avatar si ya existe
            conn.execute("UPDATE users SET avatar=? WHERE username=?", (avatar, name))
    conn.commit()

    users = conn.execute(
        "SELECT id, username FROM users WHERE username IN ('jeffsanti','dati','gogeta','salda248')"
    ).fetchall()

    # 2. Obtener partidos 11-20 jun
    matches = conn.execute(
        """SELECT * FROM matches
           WHERE kickoff>='2026-06-11' AND kickoff<='2026-06-20T23:59:00Z'
           AND home_team!='Por definir'
           ORDER BY kickoff"""
    ).fetchall()
    print(f"\n{len(matches)} partidos a simular...")

    # 3. Simular resultados reales
    finished_ids = []
    for m in matches:
        rh = random.choice([0,0,1,1,1,2,2,3,4])
        ra = random.choice([0,0,1,1,1,2,3])

        conn.execute(
            "UPDATE matches SET home_score=?, away_score=?, status='FINISHED' WHERE id=?",
            (rh, ra, m["id"])
        )
        conn.execute("DELETE FROM match_goals WHERE match_id=?", (m["id"],))

        home_sq = get_squad_names(conn, m["home_team_api_id"])
        away_sq = get_squad_names(conn, m["away_team_api_id"])

        goals = []
        for i in range(rh):
            p = random.choice(home_sq) if home_sq else f"Jugador {m['home_tla']} {i+1}"
            conn.execute(
                "INSERT INTO match_goals (match_id,player_name,team,minute,is_own_goal) VALUES (?,?,?,?,0)",
                (m["id"], p, m["home_team"], (i+1)*12)
            )
            goals.append((m["home_team"], p))
        for i in range(ra):
            p = random.choice(away_sq) if away_sq else f"Jugador {m['away_tla']} {i+1}"
            conn.execute(
                "INSERT INTO match_goals (match_id,player_name,team,minute,is_own_goal) VALUES (?,?,?,?,0)",
                (m["id"], p, m["away_team"], (i+1)*15)
            )
            goals.append((m["away_team"], p))

        conn.commit()
        finished_ids.append((m, rh, ra, goals))

    # 4. Cada usuario pronostica con distinto nivel de acierto
    accuracy = {"jeffsanti": 0.50, "dati": 0.30, "gogeta": 0.65, "salda248": 0.40}

    for u in users:
        acc = accuracy.get(u["username"], 0.40)
        for (m, rh, ra, real_goals) in finished_ids:
            roll = random.random()

            # Resultado predicho
            if roll < acc * 0.4:
                ph, pa = rh, ra                                      # exacto
            elif roll < acc:
                # Ganador correcto pero distinto marcador
                if rh > ra:   ph, pa = rh, max(0, ra - random.choice([0,1]))
                elif rh < ra: ph, pa = max(0, rh - random.choice([0,1])), ra
                else:         ph, pa = rh, ra
            else:
                ph = random.choice([0,0,1,1,1,2,2,3])
                pa = random.choice([0,0,1,1,1,2,3])

            cur = conn.execute(
                "INSERT OR REPLACE INTO predictions (user_id,match_id,home_score_pred,away_score_pred) VALUES (?,?,?,?)",
                (u["id"], m["id"], ph, pa)
            )
            pred_id = cur.lastrowid

            # Goleadores predichos (algunos correctos según accurcy)
            home_sq = get_squad_names(conn, m["home_team_api_id"])
            away_sq = get_squad_names(conn, m["away_team_api_id"])

            home_real = [g[1] for g in real_goals if g[0]==m["home_team"]]
            away_real = [g[1] for g in real_goals if g[0]==m["away_team"]]

            for pos in range(1, ph+1):
                real_p = home_real[pos-1] if pos <= len(home_real) else None
                if real_p and random.random() < acc:
                    guess = real_p        # acierto
                elif home_sq:
                    guess = random.choice(home_sq)
                else:
                    guess = f"Guess {pos}"
                conn.execute(
                    "INSERT INTO goalscorer_predictions (prediction_id,team,position,player_name,is_own_goal) VALUES (?,?,?,?,0)",
                    (pred_id, m["home_team"], pos, guess)
                )
            for pos in range(1, pa+1):
                real_p = away_real[pos-1] if pos <= len(away_real) else None
                if real_p and random.random() < acc:
                    guess = real_p
                elif away_sq:
                    guess = random.choice(away_sq)
                else:
                    guess = f"Guess {pos}"
                conn.execute(
                    "INSERT INTO goalscorer_predictions (prediction_id,team,position,player_name,is_own_goal) VALUES (?,?,?,?,0)",
                    (pred_id, m["away_team"], pos, guess)
                )

        conn.commit()

    # 5. Recalcular puntos
    for (m, *_) in finished_ids:
        recalculate_all_for_match(m["id"])

    # 6. Predicciones de premios
    award_preds = {
        "jeffsanti": ("Raul Jimenez", "Kylian Mbappé", "Yassine Bounou"),
        "dati":      ("Erling Haaland", "Jude Bellingham", "Emiliano Martinez"),
        "gogeta":    ("Kylian Mbappé", "Kylian Mbappé", "Emiliano Martinez"),
        "salda248":  ("Vinicius Jr.", "Vinicius Jr.", "Thibaut Courtois"),
    }
    for u in users:
        ap = award_preds.get(u["username"], ("", "", ""))
        conn.execute(
            "INSERT OR REPLACE INTO award_predictions(user_id,top_scorer,best_player,best_keeper) VALUES(?,?,?,?)",
            (u["id"], *ap)
        )
    conn.commit()

    # 7. Mostrar ranking rápido
    print("\n=== RANKING ===")
    rows = conn.execute("""
        SELECT u.username, COALESCE(SUM(p.points),0) pts,
               COALESCE(SUM(p.hit_exact),0) exactos,
               COALESCE(SUM(p.hit_winner),0) ganador
        FROM users u LEFT JOIN predictions p ON p.user_id=u.id
        WHERE u.username IN ('jeffsanti','dati','gogeta','salda248')
        GROUP BY u.id ORDER BY pts DESC
    """).fetchall()
    for i,r in enumerate(rows,1):
        print(f"  {i}. {r['username']:12} {r['pts']:.1f} pts | MA:{r['exactos']} GAN:{r['ganador']}")
    conn.close()


if __name__ == "__main__":
    if "--wipe" in sys.argv:
        wipe()
    else:
        seed()
