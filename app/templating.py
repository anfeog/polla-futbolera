"""Instancia única de Jinja2Templates compartida por todos los routers,
con la función crest() disponible en todas las plantillas."""
import os
from datetime import datetime
from fastapi.templating import Jinja2Templates
from app.crests import crest_url

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["crest"] = crest_url


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
