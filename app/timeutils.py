"""Utilidades de tiempo para el cierre de pronósticos."""
from datetime import datetime, timezone, timedelta

# Minutos antes del pitido en que se cierran los pronósticos.
PREDICTION_LOCK_MINUTES = 60   # regla original (partidos antes de SHORT_LOCK_FROM)
SHORT_LOCK_MINUTES = 1         # nueva regla: cierre 1 min antes del pitido
# La regla corta aplica a los partidos cuya fecha LOCAL (Colombia, UTC-5) sea
# >= esta fecha. Así "United States vs Paraguay" (13 jun 01:00 UTC = 12 jun
# 20:00 Col) mantiene 1h, y los del 13 jun Colombia ya cierran 1 min antes.
SHORT_LOCK_FROM = "2026-06-13"
_LOCAL_OFFSET = timedelta(hours=-5)   # hora de Colombia


def _parse_kickoff(kickoff: str) -> datetime:
    """Convierte el string ISO del kickoff a datetime con zona UTC."""
    k = kickoff.replace("Z", "+00:00")
    dt = datetime.fromisoformat(k)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _lock_minutes(kickoff: str) -> int:
    """1 min para partidos cuya fecha local (Colombia) sea >= SHORT_LOCK_FROM; si no, 60 min."""
    local_date = (_parse_kickoff(kickoff) + _LOCAL_OFFSET).date().isoformat()
    return SHORT_LOCK_MINUTES if local_date >= SHORT_LOCK_FROM else PREDICTION_LOCK_MINUTES


def lock_time(kickoff: str) -> datetime:
    """Momento exacto en que se cierran los pronósticos de ese partido."""
    return _parse_kickoff(kickoff) - timedelta(minutes=_lock_minutes(kickoff))


def is_locked(kickoff: str) -> bool:
    """True si ya no se puede pronosticar (pasó el cierre o ya empezó)."""
    return datetime.now(timezone.utc) >= lock_time(kickoff)


def is_past(iso: str) -> bool:
    """True si ese instante ya pasó. Usado para cerrar los premios al primer partido."""
    if not iso:
        return False
    return datetime.now(timezone.utc) >= _parse_kickoff(iso)
