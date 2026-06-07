"""Set de avatares emoji deportivos que cada jugador puede elegir."""

AVATARS = [
    "⚽", "🥅", "🧤", "👟", "🏆", "🥇",
    "🦁", "🐉", "🦅", "🐺", "🐃", "🦈",
    "🔥", "⚡", "💪", "👑", "🎯", "🚀",
    "😎", "🤠", "👽", "🤖", "🦊", "🐯",
]

DEFAULT_AVATAR = "⚽"


def is_valid(avatar: str) -> bool:
    return avatar in AVATARS
