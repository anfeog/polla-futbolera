"""
Datos FAKE para PROBAR en producción (Turso): asigna resultados y puntos
a los usuarios reales para ver las gráficas y las viñetas del podio.

Calcula puntos en línea (marcador exacto +3 / ganador +1) para minimizar
llamadas HTTP — NO toca goleadores ni premios.

Uso (con las variables de entorno TURSO_URL y TURSO_TOKEN):
    python seed_produccion.py          → siembra datos fake
    python seed_produccion.py --wipe   → limpia los datos fake

Ventana de partidos: 11–16 de junio (apertura del Mundial), varios días
para que la gráfica tenga curva.
"""
import sys, random, os

# Forzar uso de Turso si están las variables (las pasa el comando)
from app.database import get_db, init_db, _USE_TURSO

WINDOW_START = "2026-06-11"
WINDOW_END   = "2026-06-16T23:59:59Z"

TAUNTS = ["Esto ya esta ganado 😎", "Voy por ti, cuidado 👀", "Suban si pueden 🔥"]

# Distinto nivel de acierto por usuario para que las líneas se separen
ACCURACY = {0: 0.62, 1: 0.48, 2: 0.40, 3: 0.30, 4: 0.22}


def _matches(conn):
    return conn.execute(
        """SELECT * FROM matches
           WHERE kickoff >= ? AND kickoff <= ?
             AND home_team != 'Por definir' AND away_team != 'Por definir'
           ORDER BY kickoff""",
        (WINDOW_START, WINDOW_END)
    ).fetchall()


def wipe():
    conn = get_db()
    ms = _matches(conn)
    ids = [m["id"] for m in ms]
    for mid in ids:
        conn.execute("DELETE FROM predictions WHERE match_id=?", (mid,))
        conn.execute(
            "UPDATE matches SET home_score=NULL, away_score=NULL, status='SCHEDULED' WHERE id=?",
            (mid,)
        )
    conn.execute("UPDATE users SET status_msg=NULL")
    conn.commit()
    conn.close()
    print(f"Limpiado: {len(ids)} partidos reseteados y predicciones fake borradas.")


def seed():
    random.seed(2026)
    init_db()
    conn = get_db()

    users = conn.execute(
        "SELECT id, username FROM users WHERE is_admin = 0 ORDER BY id"
    ).fetchall()
    if not users:
        print("No hay usuarios reales en producción.")
        conn.close()
        return

    matches = _matches(conn)
    print(f"{len(matches)} partidos en la ventana, {len(users)} usuarios.")

    # 1. Resultados reales fake
    results = []
    for m in matches:
        rh = random.choice([0, 0, 1, 1, 1, 2, 2, 3])
        ra = random.choice([0, 0, 1, 1, 1, 2, 3])
        conn.execute(
            "UPDATE matches SET home_score=?, away_score=?, status='FINISHED' WHERE id=?",
            (rh, ra, m["id"])
        )
        results.append((m, rh, ra))
    print("Resultados asignados.")

    # 2. Predicciones + puntos en línea por usuario
    totals = {}
    for idx, u in enumerate(users):
        acc = ACCURACY.get(idx, 0.30)
        total = 0.0
        for (m, rh, ra) in results:
            roll = random.random()
            if roll < acc * 0.45:                # marcador exacto
                ph, pa = rh, ra
            elif roll < acc:                     # acierta ganador, otro marcador
                if rh > ra:   ph, pa = rh + 1, ra
                elif rh < ra: ph, pa = rh, ra + 1
                else:         ph, pa = rh, ra
            else:                                # fallo probable
                ph = random.choice([0, 1, 1, 2, 3])
                pa = random.choice([0, 1, 1, 2])

            # Puntuación en línea
            pts, hx, hw = 0.0, 0, 0
            if ph == rh and pa == ra:
                pts, hx = 3.0, 1
            elif (ph > pa and rh > ra) or (ph < pa and rh < ra) or (ph == pa and rh == ra):
                pts, hw = 1.0, 1
            total += pts

            conn.execute(
                """INSERT OR REPLACE INTO predictions
                   (user_id, match_id, home_score_pred, away_score_pred,
                    points, hit_exact, hit_winner, scorers_hit)
                   VALUES (?,?,?,?,?,?,?,0)""",
                (u["id"], m["id"], ph, pa, pts, hx, hw)
            )
        totals[u["id"]] = total
        print(f"  {u['username']:12} -> {total:.0f} pts")

    # 3. Viñetas del podio (top 3 por puntos)
    podium = sorted(users, key=lambda u: -totals[u["id"]])[:3]
    conn.execute("UPDATE users SET status_msg=NULL")
    for i, u in enumerate(podium):
        conn.execute("UPDATE users SET status_msg=? WHERE id=?", (TAUNTS[i], u["id"]))
    conn.commit()
    print("Vinetas asignadas al podio:", ", ".join(u["username"] for u in podium))

    conn.close()
    print("\nListo. Entra a la app en Render y revisa Tabla y Graficas.")


if __name__ == "__main__":
    if not _USE_TURSO:
        print("AVISO: TURSO_URL/TOKEN no estan en el entorno -> escribiria en LOCAL.")
    if "--wipe" in sys.argv:
        wipe()
    else:
        seed()
