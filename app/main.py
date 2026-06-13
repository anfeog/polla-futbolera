from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, PlainTextResponse, FileResponse
from app.database import init_db
from app.auth import get_current_user
import os, bcrypt

app = FastAPI(title="Polla Futbolera Mundial 2026")


# ── Idioma: cookie "lang" -> contextvar leída por t() en plantillas ──────────
from app.i18n import current_lang, LANGS  # noqa: E402


@app.middleware("http")
async def language_middleware(request: Request, call_next):
    lang = request.cookies.get("lang", "es")
    if lang not in LANGS:
        lang = "es"
    token = current_lang.set(lang)
    try:
        response = await call_next(request)
    finally:
        current_lang.reset(token)
    return response


@app.get("/lang/{code}")
def set_language(code: str, request: Request):
    """Cambia el idioma (cookie 1 año) y vuelve a la página anterior."""
    dest = request.headers.get("referer") or "/login"
    response = RedirectResponse(dest, status_code=303)
    if code in LANGS:
        response.set_cookie("lang", code, max_age=60 * 60 * 24 * 365)
    return response

BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Registrar rutas
from app.routes import auth, matches, predictions, ranking, admin, premios, profile
app.include_router(auth.router)
app.include_router(matches.router)
app.include_router(predictions.router)
app.include_router(ranking.router)
app.include_router(admin.router)
app.include_router(premios.router)
app.include_router(profile.router)


@app.on_event("startup")
def startup():
    init_db()
    _create_admin_if_missing()
    _start_scheduler()


def _start_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from app.football_api import update_finished_matches, fetch_and_store_matches
    from app.espn import sync_goalscorers
    import asyncio
    scheduler = AsyncIOScheduler()

    async def _sync_scorers_job():
        # sync_goalscorers es bloqueante (HTTP sync): correr en hilo aparte
        await asyncio.to_thread(sync_goalscorers)

    # Actualiza resultados (marcadores/penales) cada 5 minutos (football-data.org)
    scheduler.add_job(update_finished_matches, "interval", minutes=5, id="update_results")
    # Goleadores desde ESPN (football-data.org gratis no los da) cada 6 minutos
    scheduler.add_job(_sync_scorers_job, "interval", minutes=6, id="sync_scorers")
    # Refresca el cuadro completo cada 2 horas: rellena los equipos de las
    # fases KO en cuanto la API los define -> desbloquea sus predicciones solo.
    scheduler.add_job(fetch_and_store_matches, "interval", hours=2, id="refresh_fixture")
    scheduler.start()


def _create_admin_if_missing():
    from app.database import get_db
    admin_user = os.getenv("ADMIN_USERNAME", "admin")
    admin_pass = os.getenv("ADMIN_PASSWORD", "admin123")
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (admin_user,)).fetchone()
    if not existing:
        hashed = bcrypt.hashpw(admin_pass.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
            (admin_user, hashed)
        )
        conn.commit()
        print(f"[startup] Admin '{admin_user}' creado.")
    conn.close()


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    """Endpoint de salud para monitores (UptimeRobot). Responde 200 a GET y HEAD."""
    return PlainTextResponse("ok")


# ── PWA: servir SW y manifest desde la raíz (alcance "/") ────────────────────
@app.get("/sw.js")
def service_worker():
    return FileResponse(
        os.path.join(BASE_DIR, "static", "sw.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(
        os.path.join(BASE_DIR, "static", "manifest.webmanifest"),
        media_type="application/manifest+json",
    )


@app.get("/")
def root(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/inicio")
    return RedirectResponse("/login")
