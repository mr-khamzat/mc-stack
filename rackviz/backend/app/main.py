import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import engine, Base, SessionLocal
from .models import Device, Port, CustomDevice, PortHistory, Callout  # noqa: F401 — ensures tables are created
from .seed import seed_if_empty
from .routers import auth, rack, mc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="RackViz API", version="1.0.0", root_path="")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(rack.router)
app.include_router(mc.router)


@app.on_event("startup")
def startup():
    db = SessionLocal()
    try:
        seeded = seed_if_empty(db)
        if seeded:
            log.info("Database seeded with initial rack layout (23U, 448 ports)")
        else:
            devs = db.query(Device).count()
            log.info(f"Database ready: {devs} rack devices loaded")
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "service": "rackviz-backend"}
