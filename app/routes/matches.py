from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse  # noqa: F401
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.auth import require_login
from app.templating import templates
from app.timeutils import is_locked, lock_time, is_past, _parse_kickoff
from app.crests import slugify

router = APIRouter()

STAGE_ORDER  = ["Group Stage", "Last 32", "Last 16", "Quarter Finals", "Semi Finals", "Third Place", "Final"]
KNOCKOUT_STAGES = ["Last 32", "Last 16", "Quarter Finals", "Semi Finals", "Third Place", "Final"]
STAGE_LABELS = {
    "Group Stage":   "Fase de Grupos",
    "Last 32":       "Dieciseisavos",
    "Last 16":       "Octavos de Final",
    "Quarter Finals":"Cuartos de Final",
    "Semi Finals":   "Semifinales",
    "Third Place":   "Tercer Puesto",
    "Final":         "Final",
}
STAGE_ICONS = {
    "Group Stage":   "🏟️",
    "Last 32":       "🎲",
    "Last 16":       "⚔️",
    "Quarter Finals":"🔥",
    "Semi Finals":   "🎯",
    "Third Place":   "🥉",
    "Final":         "🏆",
}


def _stage_sort_key(s):
    return STAGE_ORDER.index(s) if s in STAGE_ORDER else 99


def group_label(g: str) -> str:
    """'GROUP_A' → 'Grupo A'"""
    return "Grupo " + g.replace("GROUP_", "") if g else ""


def _compute_standings(matches):
    """Tabla de posiciones con el desempate OFICIAL del Mundial 2026:
    Pts → enfrentamiento directo (Pts, DG, GF entre los empatados) →
    DG general → GF general.
    (Fair play y ranking FIFA no se aplican: la base no guarda tarjetas.)"""
    teams: dict = {}
    for m in matches:
        for side in ("home", "away"):
            t   = m[f"{side}_team"]
            fl  = m[f"{side}_flag"]
            tla = m[f"{side}_tla"]
            if t and t != "Por definir" and t not in teams:
                teams[t] = dict(P=0, W=0, D=0, L=0, GF=0, GA=0, GD=0, Pts=0, flag=fl, tla=tla)
    for m in matches:
        if m["home_score"] is None:
            continue
        h, a = m["home_score"], m["away_score"]
        ht, at = m["home_team"], m["away_team"]
        if ht not in teams or at not in teams:
            continue
        for t in (ht, at):
            teams[t]["P"] += 1
        teams[ht]["GF"] += h; teams[ht]["GA"] += a; teams[ht]["GD"] += h - a
        teams[at]["GF"] += a; teams[at]["GA"] += h; teams[at]["GD"] += a - h
        if h > a:
            teams[ht]["W"] += 1; teams[ht]["Pts"] += 3; teams[at]["L"] += 1
        elif h < a:
            teams[at]["W"] += 1; teams[at]["Pts"] += 3; teams[ht]["L"] += 1
        else:
            teams[ht]["D"] += 1; teams[ht]["Pts"] += 1
            teams[at]["D"] += 1; teams[at]["Pts"] += 1

    # Mini-liga del enfrentamiento directo entre un conjunto de equipos.
    def _h2h(names):
        names = set(names)
        sub = {n: {"Pts": 0, "GD": 0, "GF": 0} for n in names}
        for m in matches:
            if m["home_score"] is None:
                continue
            ht, at = m["home_team"], m["away_team"]
            if ht in names and at in names:
                h, a = m["home_score"], m["away_score"]
                sub[ht]["GF"] += h; sub[ht]["GD"] += h - a
                sub[at]["GF"] += a; sub[at]["GD"] += a - h
                if h > a:   sub[ht]["Pts"] += 3
                elif h < a: sub[at]["Pts"] += 3
                else:       sub[ht]["Pts"] += 1; sub[at]["Pts"] += 1
        return sub

    # El head-to-head solo desempata entre equipos igualados en puntos.
    h2h: dict = {}
    by_pts: dict = {}
    for n, st in teams.items():
        by_pts.setdefault(st["Pts"], []).append(n)
    for _pts, group in by_pts.items():
        h2h.update(_h2h(group))   # si un equipo está solo, queda en 0 (sin efecto)

    return sorted(
        teams.items(),
        key=lambda x: (
            -x[1]["Pts"],
            -h2h[x[0]]["Pts"], -h2h[x[0]]["GD"], -h2h[x[0]]["GF"],
            -x[1]["GD"], -x[1]["GF"],
        ),
    )


def _best_thirds(conn):
    """Tabla de mejores terceros de la fase de grupos, ordenada Pts > DG > GF."""
    groups_raw = conn.execute(
        "SELECT DISTINCT group_name FROM matches WHERE stage='Group Stage' "
        "AND group_name IS NOT NULL ORDER BY group_name"
    ).fetchall()
    thirds = []
    for gr in groups_raw:
        gn = gr["group_name"]
        gms = conn.execute(
            "SELECT * FROM matches WHERE stage='Group Stage' AND group_name=? ORDER BY kickoff",
            (gn,)
        ).fetchall()
        standings = _compute_standings(gms)
        if len(standings) >= 3:
            name, stats = standings[2]
            thirds.append({"team": name, "group": gn, "group_label": group_label(gn), **stats})
    thirds.sort(key=lambda x: (-x["Pts"], -x["GD"], -x["GF"]))
    return thirds


# Nº base de partido FIFA por fase (R32 73-88, R16 89-96, QF 97-100, SF 101-102,
# 3er puesto 103, Final 104). El orden por kickoff dentro de cada fase coincide
# con el número de partido.
STAGE_BASE = {
    "Last 32": 73, "Last 16": 89, "Quarter Finals": 97,
    "Semi Finals": 101, "Third Place": 103, "Final": 104,
}

# Orden VISUAL del cuadro según el ÁRBOL OFICIAL FIFA 2026 (no es secuencial).
BRACKET_LAYOUT = {
    "left": {
        "Last 32":        [74, 77, 73, 75, 83, 84, 81, 82],
        "Last 16":        [89, 90, 93, 94],
        "Quarter Finals": [97, 98],
        "Semi Finals":    [101],
    },
    "right": {
        "Last 32":        [76, 78, 79, 80, 86, 88, 85, 87],
        "Last 16":        [91, 92, 95, 96],
        "Quarter Finals": [99, 100],
        "Semi Finals":    [102],
    },
}

# Avance: nº de partido origen -> (nº destino, lado) según el árbol FIFA 2026.
ADVANCE_MAP = {
    74: (89, "home"), 77: (89, "away"),  73: (90, "home"),  75: (90, "away"),
    76: (91, "home"), 78: (91, "away"),  79: (92, "home"),  80: (92, "away"),
    83: (93, "home"), 84: (93, "away"),  81: (94, "home"),  82: (94, "away"),
    86: (95, "home"), 88: (95, "away"),  85: (96, "home"),  87: (96, "away"),
    89: (97, "home"), 90: (97, "away"),  93: (98, "home"),  94: (98, "away"),
    91: (99, "home"), 92: (99, "away"),  95: (100, "home"), 96: (100, "away"),
    97: (101, "home"), 98: (101, "away"), 99: (102, "home"), 100: (102, "away"),
    101: (104, "home"), 102: (104, "away"),
}


def _ko_winner(m):
    """Equipo que avanza de un partido KO terminado (o None)."""
    hs, as_ = m.get("home_score"), m.get("away_score")
    if m.get("status") != "FINISHED" or hs is None or as_ is None:
        return None
    if hs > as_:
        side = "home"
    elif as_ > hs:
        side = "away"
    else:  # empate -> lo decide quién avanza (penales)
        adv = m.get("advances_team")
        side = "home" if adv == m.get("home_team") else ("away" if adv == m.get("away_team") else None)
        if side is None:
            return None
    return {"name": m[f"{side}_team"], "flag": m[f"{side}_flag"], "tla": m[f"{side}_tla"]}


def _autofill_bracket(bynum):
    """Rellena EN MEMORIA los slots 'Por definir' con el ganador del partido que
    los alimenta (avance lógico), sin tocar la base. No pisa equipos ya definidos."""
    for src in sorted(ADVANCE_MAP):
        dst, slot = ADVANCE_MAP[src]
        sm, dm = bynum.get(src), bynum.get(dst)
        if not sm or not dm:
            continue
        w = _ko_winner(sm)
        if not w:
            continue
        if not dm.get(f"{slot}_team") or dm.get(f"{slot}_team") == "Por definir":
            dm[f"{slot}_team"] = w["name"]
            dm[f"{slot}_flag"] = w["flag"]
            dm[f"{slot}_tla"]  = w["tla"]


def _bracket_halves(conn, projected=None, include_r32=True):
    """Cuadro eliminatorio en dos mitades que se encuentran en la Final, ordenado
    según el árbol oficial FIFA 2026 y con auto-avance de ganadores.
    Si `projected` (16 partidos del R32 en orden de nº) viene dado, reemplaza el R32.
    Si `include_r32` es False, se omite la columna de Dieciseisavos (para vistas
    resumidas una vez esa ronda ya se jugó).
    Devuelve (left_cols, right_cols, final_matches, ko_rows)."""
    ko_rows = conn.execute(
        "SELECT * FROM matches WHERE stage != 'Group Stage' ORDER BY kickoff ASC"
    ).fetchall()
    by_stage: dict = defaultdict(list)
    for m in ko_rows:
        by_stage[m["stage"]].append(dict(m))
    # nº de partido FIFA -> dict del partido
    bynum = {}
    for s, base in STAGE_BASE.items():
        for i, mm in enumerate(by_stage.get(s, [])):
            bynum[base + i] = mm
    # Proyección provisional del R32 (pre-torneo): reemplaza los nº 73-88.
    if projected:
        for i, pm in enumerate(projected):
            bynum[73 + i] = pm
    # Avance lógico de ganadores a la siguiente ronda (en memoria).
    _autofill_bracket(bynum)

    stages = ("Last 32", "Last 16", "Quarter Finals", "Semi Finals")
    if not include_r32:
        stages = stages[1:]

    def cols(side):
        out = []
        for s in stages:
            out.append({
                "label": STAGE_LABELS.get(s, s), "icon": STAGE_ICONS.get(s, "⚽"),
                "matches": [bynum[n] for n in BRACKET_LAYOUT[side][s] if n in bynum],
            })
        return out

    final_matches = by_stage.get("Final", [])
    return cols("left"), cols("right"), final_matches, ko_rows


# Plantilla oficial del Round of 32 (FIFA Mundial 2026), en orden de partido 73→88.
# ("W", grupo)=1º · ("RU", grupo)=2º · ("3", {grupos})=mejor tercero de uno de esos
# grupos. La asignación EXACTA de cada tercero a su slot la fija el Anexo C de la
# FIFA; aquí se resuelve con un emparejamiento válido cualquiera (provisional).
R32_TEMPLATE = [
    (("RU", "A"), ("RU", "B")),
    (("W", "E"),  ("3", {"A", "B", "C", "D", "F"})),
    (("W", "F"),  ("RU", "C")),
    (("W", "C"),  ("RU", "F")),
    (("W", "I"),  ("3", {"C", "D", "F", "G", "H"})),
    (("RU", "E"), ("RU", "I")),
    (("W", "A"),  ("3", {"C", "E", "F", "H", "I"})),
    (("W", "L"),  ("3", {"E", "H", "I", "J", "K"})),
    (("W", "D"),  ("3", {"B", "E", "F", "I", "J"})),
    (("W", "G"),  ("3", {"A", "E", "H", "I", "J"})),
    (("RU", "K"), ("RU", "L")),
    (("W", "H"),  ("RU", "J")),
    (("W", "B"),  ("3", {"E", "F", "G", "I", "J"})),
    (("W", "J"),  ("RU", "H")),
    (("W", "K"),  ("3", {"D", "E", "I", "J", "L"})),
    (("RU", "D"), ("RU", "G")),
]


def _group_letter(group_name):
    return (group_name or "").replace("GROUP_", "")


def _projected_r32(conn):
    """Empareja PROVISIONALMENTE el Round of 32 con las posiciones actuales de los
    grupos (1º, 2º y mejores terceros). La asignación exacta de cada tercero la
    define el Anexo C de la FIFA; aquí se usa un emparejamiento válido cualquiera
    (respeta los grupos candidatos). La API reemplaza esto con los cruces reales.
    Devuelve 16 dicts con forma de partido, o None si aún no hay datos de grupos."""
    groups_raw = conn.execute(
        "SELECT DISTINCT group_name FROM matches WHERE stage='Group Stage' "
        "AND group_name IS NOT NULL ORDER BY group_name"
    ).fetchall()
    if not groups_raw:
        return None

    pos = {}   # letra de grupo -> [teamdict por posición]
    for gr in groups_raw:
        gn = gr["group_name"]
        gms = conn.execute(
            "SELECT * FROM matches WHERE stage='Group Stage' AND group_name=? ORDER BY kickoff",
            (gn,)
        ).fetchall()
        st = _compute_standings(gms)
        pos[_group_letter(gn)] = [
            {"name": name, "flag": s["flag"], "tla": s["tla"]} for name, s in st
        ]

    thirds = _best_thirds(conn)[:8]
    third_by_group = {
        _group_letter(t["group"]): {"name": t["team"], "flag": t.get("flag"), "tla": t.get("tla")}
        for t in thirds
    }
    qualified = set(third_by_group)

    # Slots de tercero a llenar y emparejamiento (backtracking) con grupos candidatos.
    third_slots = []   # (índice_partido, lado, candidatos_clasificados)
    for i, (hs, as_) in enumerate(R32_TEMPLATE):
        for side, spec in (("home", hs), ("away", as_)):
            if spec[0] == "3":
                third_slots.append((i, side, spec[1] & qualified))
    assignment = {}

    def _solve(k):
        if k == len(third_slots):
            return True
        idx, side, cands = third_slots[k]
        for g in sorted(cands):
            if g not in assignment.values():
                assignment[(idx, side)] = g
                if _solve(k + 1):
                    return True
                del assignment[(idx, side)]
        return False

    _solve(0)

    def _resolve(spec, idx, side):
        kind = spec[0]
        if kind == "W":
            lst = pos.get(spec[1]);  return lst[0] if lst and len(lst) >= 1 else None
        if kind == "RU":
            lst = pos.get(spec[1]);  return lst[1] if lst and len(lst) >= 2 else None
        g = assignment.get((idx, side))
        return third_by_group.get(g) if g else None

    def _cell(t):
        return (t["name"], t.get("flag"), t.get("tla")) if t else ("Por definir", None, None)

    out = []
    for i, (hs, as_) in enumerate(R32_TEMPLATE):
        hn, hf, hl = _cell(_resolve(hs, i, "home"))
        an, af, al = _cell(_resolve(as_, i, "away"))
        out.append({
            "id": None, "kickoff": "", "projected": True,
            "home_team": hn, "away_team": an,
            "home_flag": hf, "away_flag": af,
            "home_tla": hl,  "away_tla": al,
            "home_score": None, "away_score": None,
            "penalty_home": None, "penalty_away": None,
            "advances_team": None, "status": "TIMED",
        })
    return out


def _pred_locked(conn, matches, user_id):
    user_predictions, locked = {}, {}
    for m in matches:
        pred = conn.execute(
            "SELECT * FROM predictions WHERE user_id=? AND match_id=?",
            (user_id, m["id"])
        ).fetchone()
        user_predictions[m["id"]] = pred
        locked[m["id"]] = is_locked(m["kickoff"])
    return user_predictions, locked


def _pred_locked_bulk(conn, matches, user_id):
    """Igual que _pred_locked pero en UNA sola consulta (para listas largas)."""
    ids = [m["id"] for m in matches]
    preds = {}
    if ids:
        ph = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT * FROM predictions WHERE user_id=? AND match_id IN ({ph})",
            (user_id, *ids)
        ).fetchall()
        preds = {r["match_id"]: r for r in rows}
    user_predictions = {m["id"]: preds.get(m["id"]) for m in matches}
    locked = {m["id"]: is_locked(m["kickoff"]) for m in matches}
    return user_predictions, locked


def _calendar(matches):
    """Agrupa una lista de partidos por fecha → [(date_str, [matches])]."""
    by_date: dict = defaultdict(list)
    for m in matches:
        by_date[m["kickoff"][:10]].append(m)
    return sorted(by_date.items())


def _today():
    return datetime.now(timezone.utc).date().isoformat()


@router.get("/calendario", response_class=HTMLResponse)
def calendario(request: Request, user=Depends(require_login)):
    """Vista de calendario: todos los partidos por día con tu estado de pronóstico."""
    conn = get_db()
    matches = conn.execute("""
        SELECT * FROM matches
        WHERE home_team != 'Por definir' AND away_team != 'Por definir'
        ORDER BY kickoff ASC
    """).fetchall()
    user_predictions, locked = _pred_locked_bulk(conn, matches, user["id"])
    conn.close()
    return templates.TemplateResponse("calendario.html", {
        "request": request, "user": user,
        "calendar": _calendar(matches),
        "user_predictions": user_predictions,
        "locked": locked,
        "today": _today(),
    })


# ──────────────────────────────────────────────────────────────
# INICIO (landing: próximos partidos + contador de cierre)
# ──────────────────────────────────────────────────────────────
@router.get("/inicio", response_class=HTMLResponse)
def inicio(request: Request, user=Depends(require_login)):
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM matches
        WHERE home_team != 'Por definir' AND away_team != 'Por definir'
        ORDER BY kickoff ASC
    """).fetchall()

    upcoming = []
    any_upcoming = False   # ¿hay algún partido futuro cargado? (para diferenciar vacíos)
    for m in rows:
        if is_past(m["kickoff"]):
            continue
        any_upcoming = True
        predicted = conn.execute(
            "SELECT 1 FROM predictions WHERE user_id=? AND match_id=?",
            (user["id"], m["id"])
        ).fetchone() is not None
        # Personalizado: ocultar los que el usuario ya pronosticó,
        # así sube automáticamente el siguiente partido pendiente.
        if predicted:
            continue
        d = dict(m)
        d["predicted"] = predicted
        d["locked"]    = is_locked(m["kickoff"])
        d["lock_iso"]  = lock_time(m["kickoff"]).isoformat()
        upcoming.append(d)
        if len(upcoming) >= 5:
            break

    # ── Recordatorio: premios sin predecir (mientras sigan abiertos) ──────────
    # Mismo plazo que /premios (1h antes de Canadá–Bosnia), no el primer partido.
    from app.routes.premios import _awards_lock_kickoff
    premios_open = not is_locked(_awards_lock_kickoff(conn))
    award_row = conn.execute(
        "SELECT top_scorer FROM award_predictions WHERE user_id=?", (user["id"],)
    ).fetchone()
    premios_pending = premios_open and not (award_row and award_row["top_scorer"])

    # ── Recordatorio: comodín x2 sin usar en fases aún abiertas ───────────────
    stage_open = {}   # fase -> tiene algún partido aún pronosticable
    for m in rows:
        if not is_locked(m["kickoff"]):
            stage_open.setdefault(m["stage"], True)
    used = conn.execute("""
        SELECT DISTINCT m.stage AS stage
        FROM predictions p JOIN matches m ON m.id = p.match_id
        WHERE p.user_id = ? AND p.is_joker = 1
    """, (user["id"],)).fetchall()
    joker_stages = {r["stage"] for r in used}
    comodin_stages = [STAGE_LABELS.get(s, s) for s in stage_open if s not in joker_stages]

    # ── Partidos EN VIVO: marcador + pronósticos de todos (para el carrusel) ──
    # Un partido se considera EN VIVO si su estado lo dice, o (como respaldo, por
    # si la sincronización de estado va con retraso) si ya empezó y no terminó.
    LIVE_STATUSES = ("IN_PLAY", "PAUSED", "EXTRA_TIME", "PENALTY_SHOOTOUT", "SUSPENDED")
    DEAD_STATUSES = ("FINISHED", "CANCELLED", "POSTPONED", "AWARDED")
    now_utc = datetime.now(timezone.utc)
    candidates = conn.execute("""
        SELECT * FROM matches
        WHERE home_team != 'Por definir' AND away_team != 'Por definir'
        ORDER BY kickoff
    """).fetchall()
    live_matches = []
    for m in candidates:
        st = m["status"]
        if st in DEAD_STATUSES:
            continue
        is_live = st in LIVE_STATUSES
        if not is_live:
            try:
                ko = _parse_kickoff(m["kickoff"])
                is_live = ko <= now_utc <= ko + timedelta(hours=3)
            except Exception:
                is_live = False
        if not is_live:
            continue
        preds = conn.execute("""
            SELECT u.username, u.avatar, p.home_score_pred, p.away_score_pred, p.advances_team
            FROM predictions p JOIN users u ON u.id = p.user_id
            WHERE p.match_id = ? AND u.is_admin = 0
            ORDER BY u.username
        """, (m["id"],)).fetchall()
        live_matches.append({"m": dict(m), "preds": [dict(p) for p in preds]})

    # ── ¡Modo Colombia! Si la Tricolor juega HOY, el inicio se viste de amarillo. ──
    _COL_OFFSET = timedelta(hours=-5)   # hora de Colombia
    today_col = (datetime.now(timezone.utc) + _COL_OFFSET).date().isoformat()
    colombia_live = False
    colombia_today = False
    colombia_match_id = None
    for lm in live_matches:                      # en vivo ahora (tiene prioridad)
        cm = lm["m"]
        if "Colombia" in (cm["home_team"], cm["away_team"]):
            colombia_live = True
            colombia_match_id = cm["id"]
            break
    for r in conn.execute(
        "SELECT id, kickoff FROM matches "
        "WHERE home_team='Colombia' OR away_team='Colombia' ORDER BY kickoff"
    ).fetchall():                                # ¿juega Colombia hoy (fecha Col)?
        try:
            if (_parse_kickoff(r["kickoff"]) + _COL_OFFSET).date().isoformat() == today_col:
                colombia_today = True
                if colombia_match_id is None:
                    colombia_match_id = r["id"]
                break
        except Exception:
            pass
    colombia_yellow = colombia_today or colombia_live

    # ── Preview del cuadro eliminatorio a dos mitades (si ya hay cruces) ──────
    real_set = conn.execute(
        "SELECT 1 FROM matches WHERE stage != 'Group Stage' "
        "AND (home_team != 'Por definir' OR away_team != 'Por definir') LIMIT 1"
    ).fetchone() is not None
    # Si el R32 real aún no está definido, lo emparejamos PROVISIONALMENTE con
    # las posiciones actuales de los grupos (la API lo reemplaza el día del cruce).
    projected = _projected_r32(conn) if not real_set else None
    # En el inicio ya no interesan los dieciseisavos (fase ya jugada): se
    # muestra el cuadro arrancando desde octavos, para que se vea más compacto.
    left_cols, right_cols, final_matches, ko_rows = _bracket_halves(conn, projected, include_r32=False)
    bracket_provisional = bool(projected)
    bracket_ready = real_set or bracket_provisional

    # ── Mejores terceros: ya no se muestra en el inicio (fase de grupos
    # terminada, el cuadro ya tiene los octavos definidos). ──────────────────
    best_thirds = []

    conn.close()
    return templates.TemplateResponse("inicio.html", {
        "request": request, "user": user, "matches": upcoming,
        "any_upcoming": any_upcoming,
        "premios_pending": premios_pending,
        "comodin_stages": comodin_stages,
        "live_matches": live_matches,
        "colombia_live": colombia_live,
        "colombia_yellow": colombia_yellow,
        "colombia_match_id": colombia_match_id,
        "bracket_ready": bracket_ready,
        "bracket_provisional": bracket_provisional,
        "bracket_left":  left_cols,
        "bracket_right": list(reversed(right_cols)),   # SF→QF→L16→L32 hacia afuera
        "bracket_final": final_matches,
        "best_thirds": best_thirds,
        "thirds_qualify": 8,   # 8 mejores terceros clasifican (12 grupos)
    })


# ──────────────────────────────────────────────────────────────
# FASES (grid principal)
# ──────────────────────────────────────────────────────────────
@router.get("/partidos", response_class=HTMLResponse)
def phases_grid(request: Request, user=Depends(require_login)):
    conn = get_db()

    def progreso(where_sql, params):
        total = conn.execute(
            f"SELECT COUNT(*) c FROM matches WHERE {where_sql} AND home_team != 'Por definir'", params
        ).fetchone()["c"]
        total_all = conn.execute(
            f"SELECT COUNT(*) c FROM matches WHERE {where_sql}", params
        ).fetchone()["c"]
        predicted = conn.execute(f"""
            SELECT COUNT(*) c FROM predictions p JOIN matches m ON m.id = p.match_id
            WHERE m.{where_sql} AND m.home_team != 'Por definir' AND p.user_id=?
        """, (*params, user["id"])).fetchone()["c"]
        return total, total_all, predicted

    # Fase de Grupos
    g_total, g_total_all, g_pred = progreso("stage = ?", ("Group Stage",))

    # Fase Eliminatoria (todas las rondas KO juntas)
    ph = ",".join("?" * len(KNOCKOUT_STAGES))
    k_total, k_total_all, k_pred = progreso(f"stage IN ({ph})", tuple(KNOCKOUT_STAGES))

    conn.close()

    phases = [
        {
            "label": "Fase de Grupos", "icon": "🏟️",
            "link": "/partidos/group-stage",
            "total": g_total, "total_all": g_total_all,
            "predicted": g_pred, "pct": round(g_pred / g_total * 100) if g_total else 0,
            "available": g_total > 0, "always": False,
        },
        {
            "label": "Fase Eliminatoria", "icon": "🏆",
            "link": "/cuadro",
            "total": k_total, "total_all": k_total_all,
            "predicted": k_pred, "pct": round(k_pred / k_total * 100) if k_total else 0,
            "available": k_total > 0, "always": True,   # siempre clicable (ver el cuadro)
        },
    ]
    return templates.TemplateResponse("phases.html", {
        "request": request, "user": user, "phases": phases,
    })


# ──────────────────────────────────────────────────────────────
# CUADRO DE ELIMINATORIAS
# ──────────────────────────────────────────────────────────────
@router.get("/cuadro", response_class=HTMLResponse)
def bracket_view(request: Request, user=Depends(require_login)):
    conn = get_db()
    all_knockout = conn.execute(
        "SELECT * FROM matches WHERE stage != 'Group Stage' ORDER BY kickoff ASC"
    ).fetchall()

    user_predictions, locked = _pred_locked(conn, all_knockout, user["id"])
    third_matches = [dict(m) for m in all_knockout if m["stage"] == "Third Place"]

    # Si el Round of 32 real aún no está definido, lo emparejamos PROVISIONALMENTE
    # con las posiciones actuales de los grupos (la API lo reemplaza el día del cruce).
    real_set = any(
        m["home_team"] != "Por definir" or m["away_team"] != "Por definir"
        for m in all_knockout
    )
    projected = _projected_r32(conn) if not real_set else None
    # Cuadro ordenado por el árbol oficial FIFA 2026 + auto-avance de ganadores.
    left_cols, right_cols, final_matches, _ = _bracket_halves(conn, projected)
    provisional = bool(projected)

    conn.close()

    return templates.TemplateResponse("cuadro.html", {
        "request": request, "user": user,
        "left_cols":  left_cols,
        "right_cols": list(reversed(right_cols)),   # SF→QF→L16→L32 hacia afuera
        "final_matches":  final_matches,
        "third_matches":  third_matches,
        "provisional": provisional,
        "stage_labels": STAGE_LABELS,
        "stage_icons":  STAGE_ICONS,
        "user_predictions": user_predictions,
        "locked": locked,
    })


# ──────────────────────────────────────────────────────────────
# GRUPO INDIVIDUAL  /partidos/group-stage/grupo-a
# ──────────────────────────────────────────────────────────────
@router.get("/partidos/group-stage/{group_slug}", response_class=HTMLResponse)
def group_detail(group_slug: str, request: Request, user=Depends(require_login)):
    conn = get_db()
    all_groups = conn.execute(
        "SELECT DISTINCT group_name FROM matches WHERE stage='Group Stage' AND group_name IS NOT NULL ORDER BY group_name"
    ).fetchall()
    group_name = next(
        (r["group_name"] for r in all_groups if slugify(group_label(r["group_name"])) == group_slug),
        None
    )
    if not group_name:
        conn.close()
        raise HTTPException(404, "Grupo no encontrado")

    matches = conn.execute(
        "SELECT * FROM matches WHERE stage='Group Stage' AND group_name=? ORDER BY kickoff ASC",
        (group_name,)
    ).fetchall()

    user_predictions, locked = _pred_locked(conn, matches, user["id"])
    standings = _compute_standings(matches)
    calendar  = _calendar(matches)
    live_rows = conn.execute(
        "SELECT home_team, away_team FROM matches WHERE status IN ('IN_PLAY','PAUSED')"
    ).fetchall()
    live_teams = {r["home_team"] for r in live_rows} | {r["away_team"] for r in live_rows}
    conn.close()

    return templates.TemplateResponse("group_matches.html", {
        "request": request, "user": user,
        "calendar": calendar,
        "matches": matches,
        "user_predictions": user_predictions,
        "locked": locked,
        "group_name": group_name,
        "group_label_str": group_label(group_name),
        "standings": standings,
        "today": _today(),
        "live_teams": live_teams,
    })


# ──────────────────────────────────────────────────────────────
# FASE GENÉRICA (Group Stage → grupos grid, resto → matches)
# ──────────────────────────────────────────────────────────────
@router.get("/partidos/{slug}", response_class=HTMLResponse)
def phase_detail(slug: str, request: Request, user=Depends(require_login)):
    conn = get_db()
    stages = [r["stage"] for r in conn.execute("SELECT DISTINCT stage FROM matches").fetchall()]
    stage = next((s for s in stages if slugify(s) == slug), None)
    if not stage:
        conn.close()
        raise HTTPException(404, "Fase no encontrada")

    # ── Group Stage: cuadrícula de grupos + tabla de mejores terceros ──
    if stage == "Group Stage":
        groups_raw = conn.execute(
            "SELECT DISTINCT group_name FROM matches WHERE stage='Group Stage' AND group_name IS NOT NULL ORDER BY group_name"
        ).fetchall()

        if groups_raw:
            groups = []

            for gr in groups_raw:
                gn = gr["group_name"]
                gl = group_label(gn)
                gs = slugify(gl)
                group_matches = conn.execute(
                    "SELECT * FROM matches WHERE stage='Group Stage' AND group_name=? ORDER BY kickoff",
                    (gn,)
                ).fetchall()
                teams, seen = [], set()
                for m in group_matches:
                    for t, fl, tla in [
                        (m["home_team"], m["home_flag"], m["home_tla"]),
                        (m["away_team"], m["away_flag"], m["away_tla"]),
                    ]:
                        if t and t != "Por definir" and t not in seen:
                            teams.append({"name": t, "flag": fl, "tla": tla})
                            seen.add(t)

                total     = len(group_matches)
                finished  = sum(1 for m in group_matches if m["home_score"] is not None)
                predicted = conn.execute("""
                    SELECT COUNT(*) c FROM predictions p
                    JOIN matches m ON m.id=p.match_id
                    WHERE m.stage='Group Stage' AND m.group_name=? AND p.user_id=?
                """, (gn, user["id"])).fetchone()["c"]
                pct = round(predicted / total * 100) if total else 0

                groups.append({
                    "name": gn, "label": gl, "slug": gs,
                    "teams": teams[:4],
                    "total": total, "finished": finished,
                    "predicted": predicted, "pct": pct,
                    "standings": _compute_standings(group_matches),
                })

            # Tabla de mejores terceros (helper compartido con /inicio)
            third_place_list = _best_thirds(conn)

            # Equipos con partido en curso ahora mismo
            live_rows = conn.execute(
                "SELECT home_team, away_team FROM matches WHERE status IN ('IN_PLAY','PAUSED')"
            ).fetchall()
            live_teams = {r["home_team"] for r in live_rows} | {r["away_team"] for r in live_rows}

            conn.close()
            return templates.TemplateResponse("groups.html", {
                "request": request, "user": user,
                "groups": groups,
                "third_place": third_place_list,
                "live_teams": live_teams,
            })

    # ── Knockout / fase genérica ──
    matches = conn.execute(
        "SELECT * FROM matches WHERE stage=? ORDER BY kickoff ASC", (stage,)
    ).fetchall()
    user_predictions, locked = _pred_locked(conn, matches, user["id"])
    conn.close()

    is_knockout = stage in KNOCKOUT_STAGES
    if is_knockout:
        return templates.TemplateResponse("knockout_matches.html", {
            "request": request, "user": user,
            "matches": matches,
            "user_predictions": user_predictions,
            "locked": locked,
            "phase_label": STAGE_LABELS.get(stage, stage),
            "phase_icon":  STAGE_ICONS.get(stage, "⚽"),
        })

    # Fase de grupos sin datos de grupo (fallback lista por fecha)
    calendar = _calendar(matches)
    return templates.TemplateResponse("matches.html", {
        "request": request, "user": user,
        "calendar": calendar,
        "matches": matches,
        "user_predictions": user_predictions,
        "locked": locked,
        "phase_label": STAGE_LABELS.get(stage, stage),
        "phase_icon":  STAGE_ICONS.get(stage, "⚽"),
        "today": _today(),
    })
