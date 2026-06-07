"""
Resolución de escudos de equipos.

Prioridad:
  1. PNG local en app/static/crests/<slug>.png  (los tuyos)
  2. URL del escudo oficial que devuelve la API (guardada en la BD)
  3. None (el template muestra solo el nombre)

El <slug> es el nombre del equipo en minúsculas, sin acentos,
con espacios y símbolos convertidos en guiones.
Ej: "South Africa" -> "south-africa", "Bosnia-Herzegovina" -> "bosnia-herzegovina"
"""
import os
import re
import unicodedata

CRESTS_DIR = os.path.join(os.path.dirname(__file__), "static", "crests")


def slugify(name: str) -> str:
    if not name:
        return ""
    # Quitar acentos
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = nfkd.encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.lower().strip()
    ascii_name = re.sub(r"[^a-z0-9]+", "-", ascii_name)
    return ascii_name.strip("-")


def local_crest(team_name: str) -> str | None:
    """Devuelve la ruta web del PNG local si existe, si no None."""
    slug = slugify(team_name)
    if not slug:
        return None
    for ext in ("png", "svg", "jpg", "jpeg", "webp"):
        if os.path.exists(os.path.join(CRESTS_DIR, f"{slug}.{ext}")):
            return f"/static/crests/{slug}.{ext}"
    return None


def crest_url(team_name: str, api_url: str | None = None) -> str | None:
    """Resuelve el mejor escudo disponible para un equipo."""
    return local_crest(team_name) or api_url or None
