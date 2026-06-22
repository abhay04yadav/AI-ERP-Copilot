from fastapi import FastAPI

from app.api.routes import auth, health
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging

configure_logging(settings.log_level)

app = FastAPI(title="AI College Copilot", version="0.1.0")
register_exception_handlers(app)

app.include_router(health.router)
app.include_router(auth.router)
