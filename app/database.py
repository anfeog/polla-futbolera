import sqlite3
import os

# En producción (Fly.io) usamos /data/polla.db (volumen persistente)
# En desarrollo usamos polla.db en la raíz del proyecto
_default_db = os.path.join(os.path.dirname(__file__), "..", "polla.db")
DB_PATH = os.getenv("DATABASE_PATH", _default_db)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            avatar TEXT DEFAULT '⚽',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_id TEXT UNIQUE,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            home_team_api_id INTEGER,
            away_team_api_id INTEGER,
            home_tla TEXT,
            away_tla TEXT,
            home_flag TEXT,
            away_flag TEXT,
            kickoff TEXT NOT NULL,
            stage TEXT,
            home_score INTEGER,
            away_score INTEGER,
            status TEXT DEFAULT 'SCHEDULED'
        )
    """)

    # home_score_pred / away_score_pred guardan la predicción del marcador
    # hit_exact / hit_winner / scorers_hit = desglose para estadísticas de la tabla
    c.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            match_id INTEGER NOT NULL REFERENCES matches(id),
            home_score_pred INTEGER NOT NULL,
            away_score_pred INTEGER NOT NULL,
            points REAL DEFAULT 0,
            hit_exact INTEGER DEFAULT 0,
            hit_winner INTEGER DEFAULT 0,
            scorers_hit INTEGER DEFAULT 0,
            UNIQUE(user_id, match_id)
        )
    """)

    # Goleadores predichos por el usuario: un registro por gol, en orden
    # position = 1er gol de ese equipo, 2do gol de ese equipo, etc.
    c.execute("""
        CREATE TABLE IF NOT EXISTS goalscorer_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_id INTEGER NOT NULL REFERENCES predictions(id) ON DELETE CASCADE,
            team TEXT NOT NULL,
            position INTEGER NOT NULL,
            player_name TEXT,
            is_own_goal INTEGER DEFAULT 0
        )
    """)

    # Goleadores reales del partido (alimentado por la API)
    c.execute("""
        CREATE TABLE IF NOT EXISTS match_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL REFERENCES matches(id),
            player_name TEXT,
            team TEXT NOT NULL,
            minute INTEGER,
            is_own_goal INTEGER DEFAULT 0
        )
    """)

    # Plantillas de jugadores por selección (alimentado desde la API)
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_api_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            position TEXT,
            UNIQUE(team_api_id, name)
        )
    """)

    # Predicciones de premios del Mundial (una fila por usuario)
    c.execute("""
        CREATE TABLE IF NOT EXISTS award_predictions (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            top_scorer TEXT,
            best_player TEXT,
            best_keeper TEXT
        )
    """)

    # Ganadores reales de los premios (fila única id=1, la define el admin)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tournament_awards (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            top_scorer TEXT,
            best_player TEXT,
            best_keeper TEXT
        )
    """)
    c.execute("INSERT OR IGNORE INTO tournament_awards (id) VALUES (1)")

    conn.commit()
    _migrate(conn)
    conn.close()


def _migrate(conn):
    """Añade columnas nuevas a BD existentes sin perder datos."""
    def cols(table):
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}

    user_cols = cols("users")
    if "avatar" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT '⚽'")
    if "tutorial_seen" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN tutorial_seen INTEGER DEFAULT 0")

    pred_cols = cols("predictions")
    for col in ("hit_exact", "hit_winner", "scorers_hit"):
        if col not in pred_cols:
            conn.execute(f"ALTER TABLE predictions ADD COLUMN {col} INTEGER DEFAULT 0")

    match_cols = cols("matches")
    for col in ("home_team_api_id", "away_team_api_id"):
        if col not in match_cols:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {col} INTEGER")
    if "group_name" not in match_cols:
        conn.execute("ALTER TABLE matches ADD COLUMN group_name TEXT")
    for col in ("penalty_home", "penalty_away"):
        if col not in match_cols:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {col} INTEGER")
    if "advances_team" not in match_cols:
        conn.execute("ALTER TABLE matches ADD COLUMN advances_team TEXT")

    pred_cols = cols("predictions")
    for col in ("penalty_home", "penalty_away"):
        if col not in pred_cols:
            conn.execute(f"ALTER TABLE predictions ADD COLUMN {col} INTEGER")
    for col in ("advances_team",):
        if col not in pred_cols:
            conn.execute(f"ALTER TABLE predictions ADD COLUMN {col} TEXT")
    for col in ("advances_hit", "penalty_score_hit"):
        if col not in pred_cols:
            conn.execute(f"ALTER TABLE predictions ADD COLUMN {col} INTEGER DEFAULT 0")

    conn.commit()
