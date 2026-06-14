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


def _find_event(events: list, home: str, away: str):
    """Encuentra el evento de ESPN cuyo par de equipos coincide con el nuestro."""
    want = {_norm_team(home), _norm_team(away)}
    for e in events:
        comps = e.get("competitions", [{}])[0].get("competitors", [])
        teams = {_norm_team(c.get("team", {}).get("displayName")) for c in comps}
        if teams == want:
            return e
    return None


def _event_status_scores(event):
    """(status_name, {norm_team: score}) de un evento de ESPN."""
    comp = event.get("competitions", [{}])[0]
    status = ((comp.get("status") or event.get("status") or {}).get("type") or {}).get("name", "")
    scores = {}
    for c in comp.get("competitors", []):
        try:
            sc = int(c.get("score"))
        except (TypeError, ValueError):
            sc = None
        scores[_norm_team(c.get("team", {}).get("displayName"))] = sc
    return status, scores


def sync_goalscorers() -> int:
    """
    ESPN autosuficiente: para los partidos que ya empezaron, si ESPN los reporta
    'full-time' con sus goles completos, fija el marcador, marca FINISHED, guarda
    los goleadores (con autogoles) y recalcula los puntos — SIN depender de que
    football-data.org los marque como terminados.

    No toca partidos ya completos (marcador + nº de goles que cuadra), para
    respetar lo cargado a mano. Devuelve cuántos partidos se actualizaron.
    """
    from datetime import datetime, timezone, timedelta
    from app.scoring import recalculate_all_for_match
    from app.timeutils import _parse_kickoff

    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    matches = conn.execute("""
        SELECT id, home_team, away_team, home_score, away_score, status, kickoff
        FROM matches
        WHERE home_team != 'Por definir' AND away_team != 'Por definir'
          AND kickoff <= ?
        ORDER BY kickoff DESC LIMIT 40
    """, (now_iso,)).fetchall()

    updated = 0
    sb_cache: dict = {}

    for m in matches:
        have = conn.execute(
            "SELECT COUNT(*) c FROM match_goals WHERE match_id=?", (m["id"],)
        ).fetchone()["c"]
        cur_total = (m["home_score"] or 0) + (m["away_score"] or 0)
        # Ya completo: FINISHED y nº de goles guardados cuadra con el marcador
        if m["status"] == "FINISHED" and m["home_score"] is not None and have >= cur_total:
            continue

        # ESPN organiza por fecha de EE.UU. (atrasada vs UTC), así que un partido
        # de madrugada UTC puede aparecer bajo el día anterior. Buscar en una
        # ventana de fechas alrededor del kickoff.
        k = _parse_kickoff(m["kickoff"])
        event = None
        for delta in (0, -1, 1):
            d = (k + timedelta(days=delta)).strftime("%Y%m%d")
            if d not in sb_cache:
                try:
                    sb_cache[d] = _fetch_scoreboard(d)
                except Exception:
                    sb_cache[d] = []
            event = _find_event(sb_cache[d], m["home_team"], m["away_team"])
            if event:
                break
        if not event:
            continue

        status, scores = _event_status_scores(event)
        if status != "STATUS_FULL_TIME":
            continue  # ESPN dice que aún no termina

        nh, na = _norm_team(m["home_team"]), _norm_team(m["away_team"])
        hs, as_ = scores.get(nh), scores.get(na)
        if hs is None or as_ is None:
            continue
        total = hs + as_

        try:
            goals = _fetch_goals(event["id"])
        except Exception:
            continue
        if len(goals) != total:
            continue  # ESPN aún no tiene todos los goles: reintentar luego

        # Fijar marcador + estado FINISHED desde ESPN
        conn.execute(
            "UPDATE matches SET home_score=?, away_score=?, status='FINISHED' WHERE id=?",
            (hs, as_, m["id"])
        )
        # Reemplazar goleadores
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
