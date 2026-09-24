import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.inference.ollama_client import warm_up
from app.routers import applications, batches, extractions, reviews


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Fire-and-forget: startup shouldn't block on the model loading.
    warmup = asyncio.create_task(warm_up()) if settings.ollama_warmup_on_startup else None
    yield
    if warmup is not None:
        warmup.cancel()


app = FastAPI(title="TTB Label Review", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(extractions.router)
app.include_router(reviews.router)
app.include_router(batches.router)
app.include_router(applications.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
