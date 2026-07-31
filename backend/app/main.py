from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes import router
from app.api.learn_routes import router as learn_router
from app.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.5.0",
    description="Diagnostic automobile open source modulaire, sécurisé en lecture seule.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(router)
app.include_router(learn_router)


@app.get("/")
def root() -> dict:
    return {"name": settings.app_name, "docs": "/docs"}
