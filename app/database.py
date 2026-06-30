import sqlite3
import os
import httpx

# ── Configuración ────────────────────────────────────────────────────────────
TURSO_URL   = os.getenv("TURSO_URL", "")          # libsql://xxx.turso.io
TURSO_TOKEN = os.getenv("TURSO_TOKEN", "")
_USE_TURSO  = bool(TURSO_URL and TURSO_TOKEN)

_default_db = os.path.join(os.path.dirname(__file__), "..", "polla.db")
DB_PATH     = os.getenv("DATABASE_PATH", _default_db)


# ── Helpers Turso HTTP API ───────────────────────────────────────────────────

def _http_url():
    """libsql:// → https:// para la HTTP API de Turso."""
    return TURSO_URL.replace("libsql://", "https://")


def _to_arg(v):
    """Convierte un valor Python al formato de argumento de Turso."""
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        # La API de Turso espera el float como número JSON, no como texto
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _from_val(val):
    """Convierte un valor de Turso a Python."""
    if val["type"] == "null":
        return None
    if val["type"] == "integer":
        return int(val["value"])
    if val["type"] == "float":
        return float(val["value"])
    return val["value"]


# ── Capa de compatibilidad Turso ─────────────────────────────────────────────

class TursoRow:
    """
    Imita sqlite3.Row: acceso por nombre de columna (row["col"])
    y por índice (row[0]).
    """
    def __init__(self, columns, values):
        self._cols = list(columns)
        self._vals = list(values)
        self._dict = dict(zip(columns, values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return self._dict[key]

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def keys(self):
        return self._cols

    def get(self, key, default=None):
        return self._dict.get(key, default)


class TursoResult:
    """Cursor-like con fetchone / fetchall / iteración."""
    def __init__(self, rows, lastrowid, rowcount, description):
        self._rows = rows
        self.lastrowid = lastrowid
        self.rowcount  = rowcount
        self.description = description
        self._idx = 0

    def fetchone(self):
        if self._idx < len(self._rows):
            r = self._rows[self._idx]
            self._idx += 1
            return r
        return None

    def fetchall(self):
        r = self._rows[self._idx:]
        self._idx = len(self._rows)
        return r

    def __iter__(self):
        return iter(self._rows)


class TursoConnection:
    """
    Conexión a Turso via HTTP API.
    Misma interfaz que sqlite3.Connection para que el resto del código
    no necesite cambios.
    """
    def __init__(self, url, token):
        self._url   = url    # https://xxx.turso.io
        self._token = token
        self.row_factory = None   # interfaz compat, no usado

    # --- ejecución interna ---------------------------------------------------

    def _call(self, sql, params=()):
        stmt = {"sql": sql, "args": [_to_arg(p) for p in params]}
        resp = httpx.post(
            f"{self._url}/v2/pipeline",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type":  "application/json",
            },
            json={"requests": [
                {"type": "execute", "stmt": stmt},
                {"type": "close"},
            ]},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()["results"]
        r = results[0]
        if r["type"] == "error":
            raise Exception(r["error"]["message"])
        return r["response"]["result"]

    # --- interfaz pública ----------------------------------------------------

    def execute(self, sql, params=()):
        result   = self._call(sql, params)
        cols     = [c["name"] for c in result.get("cols", [])]
        rows     = [
            TursoRow(cols, [_from_val(v) for v in row])
            for row in result.get("rows", [])
        ]
        lastrowid = result.get("last_insert_rowid")
        if lastrowid is not None:
            lastrowid = int(lastrowid)
        rowcount  = result.get("rows_affected", -1)
        desc      = [(c,) for c in cols] if cols else None
        return TursoResult(rows, lastrowid, rowcount, desc)

    def commit(self):
        pass   # Turso auto-confirma cada sentencia

    def close(self):
        pass

    def cursor(self):
        return self   # simplificado


# ── get_db() ─────────────────────────────────────────────────────────────────

def get_db():
    if _USE_TURSO:
        return TursoConnection(_http_url(), TURSO_TOKEN)
    # Desarrollo local: SQLite normal
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Inicialización y migraciones ─────────────────────────────────────────────

def init_db():
    conn = get_db()
    c = conn

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

    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_api_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            position TEXT,
            UNIQUE(team_api_id, name)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS award_predictions (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            top_scorer TEXT,
            best_player TEXT,
            best_keeper TEXT
        )
    """)

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
    if "status_msg" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN status_msg TEXT")
    # Tienda: puntos gastados y comodín comprado en inventario (0=ninguno, 2=x2, 3=x3)
    for col in ("points_spent", "boost_owned"):
        if col not in user_cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")

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
    # Comodín (x2), "Solo tú lo predijiste" (marcador), "Solo tú" de quién avanza,
    # y el multiplicador COMPRADO de la tienda (0=ninguno, 2=x2, 3=x3).
    for col in ("is_joker", "solo_hit", "solo_advance", "boost"):
        if col not in pred_cols:
            conn.execute(f"ALTER TABLE predictions ADD COLUMN {col} INTEGER DEFAULT 0")

    # Preguntas bonus extra (campeón, subcampeón, final a penales)
    aw_cols = cols("award_predictions")
    for col in ("champion", "runner_up", "final_penalties"):
        if col not in aw_cols:
            conn.execute(f"ALTER TABLE award_predictions ADD COLUMN {col} TEXT")
    if "total_goals" not in aw_cols:
        conn.execute("ALTER TABLE award_predictions ADD COLUMN total_goals INTEGER")
    ta_cols = cols("tournament_awards")
    for col in ("champion", "runner_up", "final_penalties"):
        if col not in ta_cols:
            conn.execute(f"ALTER TABLE tournament_awards ADD COLUMN {col} TEXT")

    conn.commit()
