import httpx
import os
from app.database import get_db

API_KEY = os.getenv("FOOTBALL_API_KEY", "")
BASE_URL = "https://api.football-data.org/v4"
WC_2026_ID = 2000  # FIFA World Cup — se intenta descubrir dinámicamente si falla

HEADERS = {"X-Auth-Token": API_KEY}

# Flags emoji por nombre de equipo (ampliable)
FLAGS = {
    "Argentina": "🇦🇷", "Brazil": "🇧🇷", "France": "🇫🇷", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "Germany": "🇩🇪", "Spain": "🇪🇸", "Portugal": "🇵🇹", "Italy": "🇮🇹",
    "Netherlands": "🇳🇱", "Belgium": "🇧🇪", "Croatia": "🇭🇷", "Uruguay": "🇺🇾",
    "Colombia": "🇨🇴", "Mexico": "🇲🇽", "USA": "🇺🇸", "Canada": "🇨🇦",
    "Japan": "🇯🇵", "South Korea": "🇰🇷", "Morocco": "🇲🇦", "Senegal": "🇸🇳",
    "Australia": "🇦🇺", "Ecuador": "🇪🇨", "Switzerland": "🇨🇭", "Denmark": "🇩🇰",
    "Poland": "🇵🇱", "Serbia": "🇷🇸", "Ghana": "🇬🇭", "Cameroon": "🇨🇲",
    "Tunisia": "🇹🇳", "Saudi Arabia": "🇸🇦", "Iran": "🇮🇷", "Qatar": "🇶🇦",
}


async def _discover_wc_id(client: httpx.AsyncClient) -> int:
    """Busca el ID del Mundial 2026 entre las competiciones disponibles."""
    resp = await client.get(f"{BASE_URL}/competitions", headers=HEADERS)
    resp.raise_for_status()
    for c in resp.json().get("competitions", []):
        name = c.get("name", "").lower()
        code = c.get("code", "").upper()
        season = str(c.get("currentSeason", {}).get("startDate", ""))
        if code == "WC" or "world cup" in name:
            if "2026" in season or "2025" in season:
                return c["id"]
    # fallback al ID histórico
    return WC_2026_ID


async def fetch_and_store_matches() -> int:
    """Descarga partidos del Mundial 2026 y los guarda en la BD. Retorna cantidad importada."""
    async with httpx.AsyncClient(timeout=15) as client:
        comp_id = await _discover_wc_id(client)
        resp = await client.get(f"{BASE_URL}/competitions/{comp_id}/matches", headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()

    conn = get_db()
    imported = 0

    for m in data.get("matches", []):
        api_id = str(m["id"])
        # Partidos de eliminatorias aún sin equipos definidos llegan como null
        home = m["homeTeam"].get("name") or "Por definir"
        away = m["awayTeam"].get("name") or "Por definir"
        kickoff = m["utcDate"]
        stage = m.get("stage", "GROUP_STAGE").replace("_", " ").title()
        group_name = m.get("group")   # e.g. "GROUP_A", None for knockout stages
        status = m.get("status", "SCHEDULED")

        # IDs de equipo en la API (para cargar las plantillas)
        home_team_api_id = m["homeTeam"].get("id")
        away_team_api_id = m["awayTeam"].get("id")

        # Código de 3 letras (TLA) para el scorebug; si no hay, derivar del nombre
        home_tla = m["homeTeam"].get("tla") or (home[:3].upper() if home != "Por definir" else "???")
        away_tla = m["awayTeam"].get("tla") or (away[:3].upper() if away != "Por definir" else "???")

        # Escudo oficial que devuelve la API (fallback si no hay PNG local)
        home_crest = m["homeTeam"].get("crest")
        away_crest = m["awayTeam"].get("crest")

        score = m.get("score", {})
        full = score.get("fullTime", {})
        home_score = full.get("home")
        away_score = full.get("away")

        conn.execute("""
            INSERT INTO matches (api_id, home_team, away_team, home_team_api_id, away_team_api_id, home_tla, away_tla, home_flag, away_flag, kickoff, stage, group_name, home_score, away_score, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(api_id) DO UPDATE SET
                home_team=excluded.home_team,
                away_team=excluded.away_team,
                home_team_api_id=excluded.home_team_api_id,
                away_team_api_id=excluded.away_team_api_id,
                home_tla=excluded.home_tla,
                away_tla=excluded.away_tla,
                home_flag=excluded.home_flag,
                away_flag=excluded.away_flag,
                kickoff=excluded.kickoff,
                group_name=excluded.group_name
                -- OJO: NO se tocan home_score/away_score/status aquí.
                -- Los marcadores son responsabilidad de update_finished_matches
                -- y del admin; así el refresco del cuadro (cada 2h) rellena los
                -- equipos de las fases KO sin pisar resultados ya puestos.
        """, (api_id, home, away, home_team_api_id, away_team_api_id, home_tla, away_tla, home_crest, away_crest,
              kickoff, stage, group_name, home_score, away_score, status))
        imported += 1

    conn.commit()
    conn.close()
    return imported


async def fetch_and_store_squads(throttle: float = 6.5) -> dict:
    """Descarga la plantilla de cada selección y la guarda en `players`.
    El plan free permite ~10 req/min, por eso hay throttle entre llamadas.
    Devuelve {'teams': n_equipos, 'players': n_jugadores}."""
    import asyncio

    conn = get_db()
    rows = conn.execute("""
        SELECT DISTINCT team_api_id FROM (
            SELECT home_team_api_id AS team_api_id FROM matches WHERE home_team_api_id IS NOT NULL
            UNION
            SELECT away_team_api_id AS team_api_id FROM matches WHERE away_team_api_id IS NOT NULL
        )
    """).fetchall()
    team_ids = [r["team_api_id"] for r in rows]
    conn.close()

    total_players = 0
    teams_done = 0

    async with httpx.AsyncClient(timeout=20) as client:
        for i, tid in enumerate(team_ids):
            try:
                resp = await client.get(f"{BASE_URL}/teams/{tid}", headers=HEADERS)
                if resp.status_code != 200:
                    continue
                squad = resp.json().get("squad", []) or []
            except Exception:
                continue

            conn = get_db()
            for p in squad:
                name = (p.get("name") or "").strip()
                if not name:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO players (team_api_id, name, position) VALUES (?, ?, ?)",
                    (tid, name, p.get("position"))
                )
                total_players += 1
            conn.commit()
            conn.close()
            teams_done += 1

            if i < len(team_ids) - 1:
                await asyncio.sleep(throttle)

    return {"teams": teams_done, "players": total_players}


def get_squad(team_api_id):
    """Lista de jugadores de un equipo (para los desplegables).
    Prioridad: BD → squads.json → lista vacía."""
    if not team_api_id:
        return []
    conn = get_db()
    rows = conn.execute(
        "SELECT name, position FROM players WHERE team_api_id = ? ORDER BY name",
        (team_api_id,)
    ).fetchall()
    conn.close()
    if rows:
        return [dict(r) for r in rows]

    # Fallback: JSON cacheado localmente
    import json as _json
    json_path = os.path.join(os.path.dirname(__file__), "data", "squads.json")
    try:
        with open(json_path, encoding="utf-8") as f:
            data = _json.load(f)
        return data.get(str(team_api_id), {}).get("players", [])
    except Exception:
        return []


async def update_finished_matches():
    """Actualiza resultados: partidos terminados (recalcula puntos) y en vivo (solo marcador)."""
    from app.scoring import recalculate_all_for_match

    async with httpx.AsyncClient(timeout=15) as client:
        # Una sola llamada trae terminados + en vivo + pausados
        resp = await client.get(
            f"{BASE_URL}/competitions/{WC_2026_ID}/matches",
            headers=HEADERS,
            params={"status": "FINISHED,IN_PLAY,PAUSED"}
        )
        resp.raise_for_status()
        data = resp.json()

    conn = get_db()
    updated_ids = []  # solo los recién FINISHED recalculan puntos

    for m in data.get("matches", []):
        api_id     = str(m["id"])
        api_status = m.get("status", "")
        is_live    = api_status in ("IN_PLAY", "PAUSED")
        score      = m.get("score", {})

        # OJO: si el partido se define por penales, football-data.org mete la
        # tanda DENTRO de "fullTime" (ej. 4-5 en vez de 1-1). El marcador real
        # del partido (90/120 min) está en "regularTime" cuando existe.
        if is_live:
            current = score.get("fullTime") or score.get("halfTime") or {}
            home_score = current.get("home")
            away_score = current.get("away")
        else:
            reg = score.get("regularTime")
            full = reg if reg is not None else score.get("fullTime", {})
            home_score = full.get("home")
            away_score = full.get("away")

        if home_score is None:
            continue

        row = conn.execute(
            "SELECT id, home_score, away_score, status, home_team, away_team FROM matches WHERE api_id=?",
            (api_id,)
        ).fetchone()
        if not row:
            continue

        if is_live:
            # Actualizar marcador y estado en vivo, sin recalcular puntos.
            # Los goles SÍ se guardan: su orden (por minuto) es estable, así
            # el ranking puede mostrar puntos provisionales de goleador.
            conn.execute(
                "UPDATE matches SET home_score=?, away_score=?, status=? WHERE api_id=?",
                (home_score, away_score, api_status, api_id)
            )
            _store_match_goals(conn, row, m.get("goals", []) or [])
            continue

        # ── Partido FINISHED ───────────────────────────────────────
        penalties = score.get("penalties") or {}
        pen_home  = penalties.get("home")
        pen_away  = penalties.get("away")
        if pen_home is not None and pen_away is not None:
            advances = row["home_team"] if pen_home > pen_away else row["away_team"]
        else:
            advances = None

        already_finished = row["status"] == "FINISHED"
        score_changed    = row["home_score"] != home_score

        if not already_finished or score_changed or (pen_home is not None):
            conn.execute(
                """UPDATE matches
                   SET home_score=?, away_score=?, status='FINISHED',
                       penalty_home=?, penalty_away=?, advances_team=?
                   WHERE api_id=?""",
                (home_score, away_score, pen_home, pen_away, advances, api_id)
            )
            if not already_finished or score_changed:
                updated_ids.append(row["id"])

        # Guardar goles del partido terminado
        _store_match_goals(conn, row, m.get("goals", []) or [])

    conn.commit()
    conn.close()

    for match_id in updated_ids:
        recalculate_all_for_match(match_id)

    return len(updated_ids)


def _store_match_goals(conn, row, api_goals):
    """Reemplaza los goles de un partido con los de la API (orden por minuto estable)."""
    if not api_goals:
        return
    conn.execute("DELETE FROM match_goals WHERE match_id=?", (row["id"],))
    for g in api_goals:
        scorer_obj  = g.get("scorer") or {}
        team_obj    = g.get("team")   or {}
        player_name = (scorer_obj.get("name") or scorer_obj.get("shortName") or "").strip()
        team_name   = (team_obj.get("name") or "").strip()
        minute      = g.get("minute")
        goal_type   = g.get("type", "REGULAR")
        is_own      = 1 if goal_type == "OWN_GOAL" else 0
        if not team_name:
            team_name = row["home_team"] if g.get("team", {}).get("id") else row["away_team"]
        conn.execute(
            "INSERT INTO match_goals (match_id, player_name, team, minute, is_own_goal) VALUES (?,?,?,?,?)",
            (row["id"], player_name, team_name, minute, is_own)
        )
