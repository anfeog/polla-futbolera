"""Instancia única de Jinja2Templates compartida por todos los routers,
con la función crest() disponible en todas las plantillas."""
import os
from datetime import datetime
from fastapi.templating import Jinja2Templates
from app.crests import crest_url
from app.team_colors import team_gradient
from app.i18n import t, get_lang, LANGS, LANG_FLAGS

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["crest"] = crest_url
templates.env.globals["team_gradient"] = team_gradient
templates.env.globals["t"] = t
templates.env.globals["get_lang"] = get_lang
templates.env.globals["LANGS"] = LANGS
templates.env.globals["LANG_FLAGS"] = LANG_FLAGS


# ── Nacionalidad de cada jugador (para el roast del "vendepatria") ────────────
# Todos son colombianos, excepto los usuarios listados aquí.
PLAYER_COUNTRIES = {
    "iago": "Brazil",
}


def player_country(username: str) -> str:
    return PLAYER_COUNTRIES.get((username or "").strip().lower(), "Colombia")


def is_vendepatria(username, home_team, away_team, home_pred, away_pred,
                   advances_team=None, stage=None) -> bool:
    """True si el jugador pronosticó a SU PROPIA selección perdiendo.

    - Fase de grupos: un EMPATE ya cuenta (no apostó por su selección a ganar).
    - Fase eliminatoria: un empate cuenta solo si predijo que su selección NO
      avanza (pierde en penales). Si predijo que avanza (gana penales), no cuenta.
    """
    if home_pred is None or away_pred is None:
        return False
    country = player_country(username)
    if country not in (home_team, away_team):
        return False
    if home_pred == away_pred:
        if stage and stage != "Group Stage":
            # Eliminatoria: solo si predijo que su selección no avanza.
            return bool(advances_team) and advances_team != country
        # Fase de grupos: el empate ya es vendepatria.
        return True
    if country == home_team:
        return home_pred < away_pred
    return away_pred < home_pred


templates.env.globals["player_country"] = player_country
templates.env.globals["is_vendepatria"] = is_vendepatria


def show_incoming_call_prank() -> bool:
    """Easter egg: el día que juega Paraguay vs Francia, al abrir la app se
    simula una 'llamada entrante' (broma). Se muestra todo ese día, hora
    Colombia (UTC-5), igual que el modo amarillo de Colombia."""
    from datetime import datetime, timezone, timedelta
    from app.database import get_db
    from app.timeutils import _parse_kickoff
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT kickoff FROM matches
            WHERE (home_team='Paraguay' AND away_team='France')
               OR (home_team='France' AND away_team='Paraguay')
            LIMIT 1
        """).fetchone()
    finally:
        conn.close()
    if not row:
        return False
    col_offset = timedelta(hours=-5)
    today_col = (datetime.now(timezone.utc) + col_offset).date().isoformat()
    try:
        match_day_col = (_parse_kickoff(row["kickoff"]) + col_offset).date().isoformat()
    except Exception:
        return False
    return match_day_col == today_col


templates.env.globals["show_incoming_call_prank"] = show_incoming_call_prank


def _format_date(date_str: str) -> str:
    """'2026-06-11' → 'Jueves 11 Jun'"""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        days = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        return f"{days[d.weekday()]} {d.day} {months[d.month - 1]}"
    except Exception:
        return date_str


templates.env.filters["date_fmt"] = _format_date
