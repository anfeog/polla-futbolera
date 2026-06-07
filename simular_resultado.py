"""
Script de PRUEBA para simular el resultado de un partido y verificar el scoring.
NO usar en producción — sirve para testear puntos antes de que empiece el Mundial.

Uso:
    python simular_resultado.py <match_id> <home_score> <away_score>

Luego pide los goleadores reales en orden. Ejemplo:
    python simular_resultado.py 1 2 1
"""
import sys
from dotenv import load_dotenv
load_dotenv()
from app.database import get_db
from app.scoring import recalculate_all_for_match


def simular(match_id: int, home_score: int, away_score: int, goals: list):
    """goals = lista de tuplas (team_name, player_name, minute, is_own_goal)"""
    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if not match:
        print(f"No existe el partido {match_id}")
        return

    conn.execute(
        "UPDATE matches SET home_score=?, away_score=?, status='FINISHED' WHERE id=?",
        (home_score, away_score, match_id)
    )
    conn.execute("DELETE FROM match_goals WHERE match_id=?", (match_id,))
    for team, player, minute, is_own in goals:
        conn.execute(
            "INSERT INTO match_goals (match_id, player_name, team, minute, is_own_goal) VALUES (?,?,?,?,?)",
            (match_id, player, team, minute, is_own)
        )
    conn.commit()
    conn.close()

    recalculate_all_for_match(match_id)
    print(f"Resultado simulado: {match['home_team']} {home_score}-{away_score} {match['away_team']}")
    print("Goles:", goals)

    # Mostrar puntos resultantes
    conn = get_db()
    rows = conn.execute("""
        SELECT u.username, p.points
        FROM predictions p JOIN users u ON u.id = p.user_id
        WHERE p.match_id = ?
        ORDER BY p.points DESC
    """, (match_id,)).fetchall()
    print("\nPuntos por jugador en este partido:")
    for r in rows:
        print(f"  {r['username']}: {r['points']} pts")
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    mid = int(sys.argv[1])
    hs = int(sys.argv[2])
    as_ = int(sys.argv[3])

    conn = get_db()
    match = conn.execute("SELECT * FROM matches WHERE id = ?", (mid,)).fetchone()
    conn.close()
    if not match:
        print(f"No existe el partido {mid}")
        sys.exit(1)

    print(f"Simulando: {match['home_team']} {hs}-{as_} {match['away_team']}")
    print("\nIntroduce los goleadores en orden (minuto creciente).")
    goals = []
    home_team, away_team = match["home_team"], match["away_team"]

    for i in range(hs):
        name = input(f"  Gol {i+1} de {home_team} - jugador (o 'og' para autogol): ").strip()
        is_own = 1 if name.lower() == "og" else 0
        goals.append((home_team, None if is_own else name, (i + 1) * 10, is_own))
    for i in range(as_):
        name = input(f"  Gol {i+1} de {away_team} - jugador (o 'og' para autogol): ").strip()
        is_own = 1 if name.lower() == "og" else 0
        goals.append((away_team, None if is_own else name, (i + 1) * 10, is_own))

    simular(mid, hs, as_, goals)
