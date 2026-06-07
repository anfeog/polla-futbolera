"""Utilidades de tiempo para el cierre de pronósticos."""
from datetime import datetime, timezone, timedelta

# Los pronósticos se cierran esta cantidad de minutos ANTES del inicio del partido
PREDICTION_LOCK_MINUTES = 60


def _parse_kickoff(kickoff: str) -> datetime:
    """Convierte el string ISO del kickoff a datetime con zona UTC."""
    k = kickoff.replace("Z", "+00:00")
    dt = datetime.fromisoformat(k)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def lock_time(kickoff: str) -> datetime:
    """Momento exacto en que se cierran los pronósticos de ese partido."""
    return _parse_kickoff(kickoff) - timedelta(minutes=PREDICTION_LOCK_MINUTES)


def is_locked(kickoff: str) -> bool:
    """True si ya no se puede pronosticar (faltan <1h o ya empezó)."""
    return datetime.now(timezone.utc) >= lock_time(kickoff)


def is_past(iso: str) -> bool:
    """True si ese instante ya pasó. Usado para cerrar los premios al primer partido."""
    if not iso:
        return False
    return datetime.now(timezone.utc) >= _parse_kickoff(iso)
