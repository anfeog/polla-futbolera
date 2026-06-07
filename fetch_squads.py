"""
Descarga las plantillas de los 48 equipos del Mundial 2026.
Guarda en la BD (tabla players) + en app/data/squads.json (backup permanente).
Con 10 req/min de API gratuita tarda ~5 min.

Uso: python fetch_squads.py
     python fetch_squads.py --force   (re-descarga aunque ya existan)
"""
import os, sys, time, json
from dotenv import load_dotenv
load_dotenv()

# Windows cp1252 fix
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx
from app.database import get_db, init_db

API_KEY   = os.getenv("FOOTBALL_API_KEY", "")
BASE_URL  = "https://api.football-data.org/v4"
HEADERS   = {"X-Auth-Token": API_KEY}
THROTTLE  = 6.5
DATA_DIR  = os.path.join(os.path.dirname(__file__), "app", "data")
JSON_PATH = os.path.join(DATA_DIR, "squads.json")
FORCE     = "--force" in sys.argv


def load_existing_json():
    try:
        with open(JSON_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    init_db()
    conn = get_db()

    rows = conn.execute("""
        SELECT DISTINCT team_api_id, name FROM (
            SELECT home_team_api_id AS team_api_id, home_team AS name
              FROM matches WHERE home_team_api_id IS NOT NULL AND home_team != 'Por definir'
            UNION
            SELECT away_team_api_id, away_team
              FROM matches WHERE away_team_api_id IS NOT NULL AND away_team != 'Por definir'
        ) ORDER BY name
    """).fetchall()

    team_map   = {r["team_api_id"]: r["name"] for r in rows}
    all_squads = load_existing_json()

    already_in_db = set()
    if not FORCE:
        for tid in team_map:
            n = conn.execute("SELECT COUNT(*) c FROM players WHERE team_api_id=?", (tid,)).fetchone()["c"]
            if n > 0:
                already_in_db.add(tid)

    to_fetch = [tid for tid in team_map if tid not in already_in_db]
    print(f"Equipos en DB   : {len(team_map)}")
    print(f"Ya cargados     : {len(already_in_db)}")
    print(f"A descargar     : {len(to_fetch)}")
    if to_fetch:
        print(f"Tiempo estimado : ~{len(to_fetch) * THROTTLE / 60:.0f} min\n")
    else:
        print("OK - Todos los equipos ya estan en la BD. Usa --force para re-descargar.\n")

    for i, tid in enumerate(to_fetch):
        team_name = team_map[tid]
        try:
            r = httpx.get(f"{BASE_URL}/teams/{tid}", headers=HEADERS, timeout=20)
            if r.status_code == 429:
                print("  [rate-limit] esperando 60 s...")
                time.sleep(60)
                r = httpx.get(f"{BASE_URL}/teams/{tid}", headers=HEADERS, timeout=20)
            if r.status_code != 200:
                print(f"  [ERROR] {team_name} ({tid}): HTTP {r.status_code}")
                continue

            squad = r.json().get("squad", []) or []
            players = []
            for p in squad:
                name = (p.get("name") or "").strip()
                pos  = p.get("position")
                if not name:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO players (team_api_id, name, position) VALUES (?,?,?)",
                    (tid, name, pos)
                )
                players.append({"name": name, "position": pos})
            conn.commit()

            all_squads[str(tid)] = {"team": team_name, "players": players}
            save_json(all_squads)
            print(f"  OK [{i+1}/{len(to_fetch)}] {team_name}: {len(players)} jugadores")

        except Exception as e:
            print(f"  ERROR {team_name}: {e}")

        if i < len(to_fetch) - 1:
            time.sleep(THROTTLE)

    # Asegurar que equipos ya en BD tambien esten en el JSON
    for tid in already_in_db:
        if str(tid) not in all_squads:
            rows_p = conn.execute(
                "SELECT name, position FROM players WHERE team_api_id=?", (tid,)
            ).fetchall()
            all_squads[str(tid)] = {
                "team": team_map[tid],
                "players": [{"name": r["name"], "position": r["position"]} for r in rows_p]
            }
    save_json(all_squads)

    conn.close()
    total = sum(len(v["players"]) for v in all_squads.values())
    print(f"\nListo: {len(all_squads)} equipos, {total} jugadores -> {JSON_PATH}")


if __name__ == "__main__":
    main()
