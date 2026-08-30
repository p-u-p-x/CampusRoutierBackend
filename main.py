import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import engine
import models

# Import routers (use correct filenames)
from routers import auth_routes, admin, student, driver, system

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Campus Routier", version="6.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Include routers
app.include_router(auth_routes.router)
app.include_router(admin.router)
app.include_router(student.router)
app.include_router(driver.router)
app.include_router(system.router)


@app.get("/")
def root():
    return {"message": "Campus Routier Running"}