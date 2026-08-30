from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import models
import schemas
import auth
from auth import get_db, require_admin

router = APIRouter(tags=["System"])


@router.get("/users", response_model=list[schemas.UserMinimal])
def get_users(
    role: str = Query(None, description="Filter by role"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    query = db.query(models.User)
    if role:
        query = query.filter(models.User.role == role)
    users = query.all()
    return [{"id": u.id, "username": u.username, "role": u.role} for u in users]


@router.get("/vans", response_model=list[schemas.VanResponse])
def get_vans(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    vans = db.query(models.Van).all()
    return vans