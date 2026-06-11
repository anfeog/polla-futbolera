from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse  # noqa: F401
from collections import defaultdict
from datetime import datetime, timezone

from app.database import get_db
from app.auth import require_login
from app.templating import templates
from app.timeutils import is_locked, lock_time, is_past
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
    """Tabla de posiciones a partir de los partidos con resultado."""
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
    return sorted(teams.items(), key=lambda x: (-x[1]["Pts"], -x[1]["GD"], -x[1]["GF"]))


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


def _calendar(matches):
    """Agrupa una lista de partidos por fecha → [(date_str, [matches])]."""
    by_date: dict = defaultdict(list)
    for m in matches:
        by_date[m["kickoff"][:10]].append(m)
    return sorted(by_date.items())


def _today():
    return datetime.now(timezone.utc).date().isoformat()


@router.get("/calendario", response_class=HTMLResponse)
def calendario_redirect(request: Request, user=Depends(require_login)):
    """El calendario fue integrado en las fases — redirigir a partidos."""
    return RedirectResponse("/partidos", status_code=302)


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
    first_k = conn.execute(
        "SELECT MIN(kickoff) k FROM matches WHERE home_team != 'Por definir'"
    ).fetchone()["k"]
    premios_open = (not is_past(first_k)) if first_k else True
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

    conn.close()
    return templates.TemplateResponse("inicio.html", {
        "request": request, "user": user, "matches": upcoming,
        "any_upcoming": any_upcoming,
        "premios_pending": premios_pending,
        "comodin_stages": comodin_stages,
    })


# ──────────────────────────────────────────────────────────────
# FASES (grid principal)
# ──────────────────────────────────────────────────────────────
@router.get("/partidos", response_class=HTMLResponse)
def phases_grid(request: Request, user=Depends(require_login)):
    conn = get_db()
    stages = [r["stage"] for r in conn.execute("SELECT DISTINCT stage FROM matches").fetchall()]
    stages.sort(key=_stage_sort_key)

    phases = []
    for stage in stages:
        total = conn.execute(
            "SELECT COUNT(*) c FROM matches WHERE stage=? AND home_team != 'Por definir'", (stage,)
        ).fetchone()["c"]
        total_all = conn.execute(
            "SELECT COUNT(*) c FROM matches WHERE stage=?", (stage,)
        ).fetchone()["c"]
        predicted = conn.execute("""
            SELECT COUNT(*) c FROM predictions p
            JOIN matches m ON m.id = p.match_id
            WHERE m.stage=? AND m.home_team != 'Por definir' AND p.user_id=?
        """, (stage, user["id"])).fetchone()["c"]
        pct = round(predicted / total * 100) if total else 0
        phases.append({
            "stage": stage, "slug": slugify(stage),
            "label": STAGE_LABELS.get(stage, stage),
            "icon":  STAGE_ICONS.get(stage, "⚽"),
            "total": total, "total_all": total_all,
            "predicted": predicted, "pct": pct,
            "available": total > 0,
        })

    conn.close()
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

    by_stage: dict = defaultdict(list)
    for m in all_knockout:
        by_stage[m["stage"]].append(m)

    # Dividir cada ronda en mitad izquierda y mitad derecha
    HALF_STAGES = ["Last 32", "Last 16", "Quarter Finals", "Semi Finals"]
    left_cols, right_cols = [], []
    for stage in HALF_STAGES:
        ms = by_stage.get(stage, [])
        mid = len(ms) // 2
        left_cols.append({"stage": stage, "matches": ms[:mid]})
        right_cols.append({"stage": stage, "matches": ms[mid:]})

    final_matches   = by_stage.get("Final", [])
    third_matches   = by_stage.get("Third Place", [])

    conn.close()

    return templates.TemplateResponse("cuadro.html", {
        "request": request, "user": user,
        "left_cols":  left_cols,
        "right_cols": list(reversed(right_cols)),   # SF→QF→L16→L32 hacia afuera
        "final_matches":  final_matches,
        "third_matches":  third_matches,
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
            groups, third_place_list = [], []

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

                # Terceros para la tabla de mejores terceros
                standings = _compute_standings(group_matches)
                if len(standings) >= 3:
                    t3_name, t3_stats = standings[2]
                    third_place_list.append({
                        "team": t3_name, "group": gn, "group_label": gl,
                        **t3_stats
                    })

            # Ordenar terceros: pts > DG > GF
            third_place_list.sort(key=lambda x: (-x["Pts"], -x["GD"], -x["GF"]))

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
