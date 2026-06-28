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


def is_vendepatria(username, home_team, away_team, home_pred, away_pred) -> bool:
    """True si el jugador pronosticó a SU PROPIA selección perdiendo."""
    if home_pred is None or away_pred is None:
        return False
    country = player_country(username)
    if country == home_team:
        return home_pred < away_pred
    if country == away_team:
        return away_pred < home_pred
    return False


templates.env.globals["player_country"] = player_country
templates.env.globals["is_vendepatria"] = is_vendepatria


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
