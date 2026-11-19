from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.routers import devices, growth, health, home, runs, users

settings = get_settings()

app = FastAPI(
    title="Pacebeat API",
    version="1.0.0",
    description="Pacebeat 러닝 & 선택형 스마트 인솔 자세 리포트 백엔드 API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(health.router)
app.include_router(users.router)
app.include_router(devices.router)
app.include_router(home.router)
app.include_router(runs.router)
app.include_router(growth.router)
