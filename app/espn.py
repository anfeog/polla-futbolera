"""
Goleadores desde la API pública (no oficial) de ESPN.

football-data.org (gratis) da marcadores pero NO goleadores. ESPN sí los da,
completos y gratis, en su endpoint de resumen. Aquí los sincronizamos para los
partidos ya FINISHED y recalculamos los puntos de goleador.

Endpoints:
  scoreboard?dates=YYYYMMDD  -> partidos del día (para encontrar el event id)
  summary?event=<id>         -> keyEvents con los goles (jugador, minuto, equipo)
"""
import unicodedata
import httpx

from app.database import get_db

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"

# Alias para nombres que ESPN escribe distinto a football-data.org
_ALIASES = {
    "turkiye": "turkey",
    "drcongo": "congodr",
}


def _norm_team(s: str) -> str:
    """Normaliza nombre de selección para comparar entre fuentes."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("islands", "")
    s = "".join(ch for ch in s if ch.isalnum())
    return _ALIASES.get(s, s)


def _parse_minute(disp: str) -> int:
    """'9\\'' -> 9, '90+3\\'' -> 90 (orden cronológico aproximado)."""
    if not disp:
        return 999
    d = disp.replace("'", "").strip()
    if "+" in d:
        d = d.split("+", 1)[0]
    try:
        return int(d)
    except ValueError:
        return 999


def _fetch_scoreboard(date_yyyymmdd: str) -> list:
    r = httpx.get(f"{ESPN_BASE}/scoreboard", params={"dates": date_yyyymmdd}, timeout=20)
    r.raise_for_status()
    return r.json().get("events", []) or []


def _fetch_goals(event_id: str) -> list:
    """Lista de goles de un partido: [{team, scorer, minute, is_own_goal}], ordenada."""
    r = httpx.get(f"{ESPN_BASE}/summary", params={"event": event_id}, timeout=20)
    r.raise_for_status()
    data = r.json()
    goals = []
    for e in (data.get("keyEvents") or []):
        ty = ((e.get("type") or {}).get("text") or "")
        tyl = ty.lower()
        if "goal" not in tyl:
            continue
        if "disallow" in tyl or "cancel" in tyl or "no goal" in tyl:
            continue
        parts = e.get("participants") or []
        scorer = parts[0].get("athlete", {}).get("displayName") if parts else None
        goals.append({
            "team": (e.get("team") or {}).get("displayName"),
            "scorer": (scorer or "").strip(),
            "minute": _parse_minute((e.get("clock") or {}).get("displayValue")),
            "is_own_goal": 1 if (e.get("ownGoal") or "own goal" in tyl) else 0,
        })
    goals.sort(key=lambda g: g["minute"])
    return goals


def _find_event_id(events: list, home: str, away: str):
    """Encuentra el event id de ESPN cuyo par de equipos coincide con el nuestro."""
    want = {_norm_team(home), _norm_team(away)}
    for e in events:
        comps = e.get("competitions", [{}])[0].get("competitors", [])
        teams = {_norm_team(c.get("team", {}).get("displayName")) for c in comps}
        if teams == want:
            return e["id"]
    return None


def sync_goalscorers() -> int:
    """
    Para cada partido FINISHED sin sus goleadores completos, los baja de ESPN
    y recalcula los puntos. Devuelve cuántos partidos se actualizaron.
    Solo aplica si ESPN tiene los goles COMPLETOS (= total del marcador), para
    no repartir puntos con datos parciales.
    """
    from app.scoring import recalculate_all_for_match

    conn = get_db()
    matches = conn.execute("""
        SELECT id, home_team, away_team, home_score, away_score, kickoff
        FROM matches
        WHERE status = 'FINISHED' AND home_score IS NOT NULL
    """).fetchall()

    updated = 0
    sb_cache: dict = {}

    for m in matches:
        total = (m["home_score"] or 0) + (m["away_score"] or 0)
        if total == 0:
            continue
        have = conn.execute(
            "SELECT COUNT(*) c FROM match_goals WHERE match_id=?", (m["id"],)
        ).fetchone()["c"]
        if have >= total:
            continue  # ya está completo (por ESPN o manual)

        date = m["kickoff"][:10].replace("-", "")
        if date not in sb_cache:
            try:
                sb_cache[date] = _fetch_scoreboard(date)
            except Exception:
                sb_cache[date] = []
        event_id = _find_event_id(sb_cache[date], m["home_team"], m["away_team"])
        if not event_id:
            continue

        try:
            goals = _fetch_goals(event_id)
        except Exception:
            continue
        if len(goals) != total:
            continue  # ESPN aún no tiene todos: reintentar en el próximo ciclo

        nh, na = _norm_team(m["home_team"]), _norm_team(m["away_team"])
        conn.execute("DELETE FROM match_goals WHERE match_id=?", (m["id"],))
        for g in goals:
            gt = _norm_team(g["team"])
            team_name = m["home_team"] if gt == nh else (m["away_team"] if gt == na else m["home_team"])
            conn.execute(
                "INSERT INTO match_goals (match_id, player_name, team, minute, is_own_goal) "
                "VALUES (?,?,?,?,?)",
                (m["id"], g["scorer"], team_name, g["minute"], g["is_own_goal"])
            )
        conn.commit()
        recalculate_all_for_match(m["id"])
        updated += 1

    conn.close()
    return updated
