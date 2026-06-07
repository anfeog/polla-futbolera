from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from app.database import init_db
from app.auth import get_current_user
import os, bcrypt

app = FastAPI(title="Polla Futbolera Mundial 2026")

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
    from app.football_api import update_finished_matches
    scheduler = AsyncIOScheduler()
    # Actualiza resultados cada 5 minutos durante el Mundial
    scheduler.add_job(update_finished_matches, "interval", minutes=5, id="update_results")
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


@app.get("/")
def root(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/partidos")
    return RedirectResponse("/login")
