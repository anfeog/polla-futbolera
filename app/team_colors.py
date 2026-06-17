"""
Colores de bandera por país, para pintar los filos del marcador en vivo.

Cada equipo mapea a una lista de 2-3 colores (hex) tomados de su bandera.
La clave es el slug del nombre (ver crests.slugify): minúsculas, sin acentos
y con guiones. Equipos desconocidos caen en un gris neutro.
"""
from app.crests import slugify

# Colores principales de cada bandera (orden visual de arriba a abajo).
_COLORS: dict[str, list[str]] = {
    "algeria": ["#006233", "#ffffff", "#d21034"],
    "argentina": ["#74acdf", "#ffffff", "#74acdf"],
    "australia": ["#012169", "#ffffff", "#e4002b"],
    "austria": ["#ed2939", "#ffffff", "#ed2939"],
    "belgium": ["#000000", "#fae042", "#ed2939"],
    "bosnia-herzegovina": ["#002395", "#fecb00"],
    "brazil": ["#009c3b", "#ffdf00", "#002776"],
    "canada": ["#ff0000", "#ffffff", "#ff0000"],
    "cape-verde-islands": ["#003893", "#ffffff", "#cf2027"],
    "colombia": ["#fcd116", "#003893", "#ce1126"],
    "congo-dr": ["#007fff", "#f7d618", "#ce1021"],
    "croatia": ["#ff0000", "#ffffff", "#171796"],
    "curacao": ["#002b7f", "#f9e814", "#002b7f"],
    "czechia": ["#11457e", "#ffffff", "#d7141a"],
    "ecuador": ["#ffd100", "#0072ce", "#ef3340"],
    "egypt": ["#ce1126", "#ffffff", "#000000"],
    "england": ["#ffffff", "#ce1124", "#ffffff"],
    "france": ["#002395", "#ffffff", "#ed2939"],
    "germany": ["#000000", "#dd0000", "#ffce00"],
    "ghana": ["#ce1126", "#fcd116", "#006b3f"],
    "haiti": ["#00209f", "#d21034"],
    "iran": ["#239f40", "#ffffff", "#da0000"],
    "iraq": ["#ce1126", "#ffffff", "#000000"],
    "ivory-coast": ["#f77f00", "#ffffff", "#009e60"],
    "japan": ["#ffffff", "#bc002d", "#ffffff"],
    "jordan": ["#000000", "#ffffff", "#007a3d"],
    "mexico": ["#006847", "#ffffff", "#ce1126"],
    "morocco": ["#c1272d", "#006233"],
    "netherlands": ["#ae1c28", "#ffffff", "#21468b"],
    "new-zealand": ["#00247d", "#ffffff", "#cc142b"],
    "norway": ["#ba0c2f", "#ffffff", "#00205b"],
    "panama": ["#005293", "#ffffff", "#d21034"],
    "paraguay": ["#d52b1e", "#ffffff", "#0038a8"],
    "portugal": ["#006600", "#ff0000"],
    "qatar": ["#8a1538", "#ffffff", "#8a1538"],
    "saudi-arabia": ["#006c35", "#ffffff", "#006c35"],
    "scotland": ["#005eb8", "#ffffff", "#005eb8"],
    "senegal": ["#00853f", "#fdef42", "#e31b23"],
    "south-africa": ["#007a4d", "#ffb612", "#de3831"],
    "south-korea": ["#ffffff", "#cd2e3a", "#0047a0"],
    "spain": ["#aa151b", "#f1bf00", "#aa151b"],
    "sweden": ["#006aa7", "#fecc00", "#006aa7"],
    "switzerland": ["#d52b1e", "#ffffff", "#d52b1e"],
    "tunisia": ["#e70013", "#ffffff", "#e70013"],
    "turkey": ["#e30a17", "#ffffff", "#e30a17"],
    "united-states": ["#3c3b6e", "#ffffff", "#b22234"],
    "uruguay": ["#0038a8", "#ffffff", "#fcd116"],
    "uzbekistan": ["#1eb53a", "#ffffff", "#0099b5"],
}

_NEUTRAL = ["#94a3b8", "#475569"]


def team_colors(team_name: str) -> list[str]:
    """Lista de colores (hex) de la bandera del país; gris neutro si no se conoce."""
    return _COLORS.get(slugify(team_name), _NEUTRAL)


def team_gradient(team_name: str) -> str:
    """Gradiente CSS vertical difuminado con los colores de la bandera, para el filo del marcador."""
    cols = team_colors(team_name)
    n = len(cols)
    if n == 1:
        return f"linear-gradient(to bottom, {cols[0]}, {cols[0]})"
    stops = []
    for i, c in enumerate(cols):
        pos = round(i / (n - 1) * 100)
        stops.append(f"{c} {pos}%")
    return "linear-gradient(to bottom, " + ", ".join(stops) + ")"
