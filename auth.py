from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import models
import os
import schemas
from database import SessionLocal

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")  # CHANGE IN PRODUCTION!
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password[:72], hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password[:72])


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[schemas.TokenData]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        role = payload.get("role")
        student_id = payload.get("student_id")
        if username is None or role is None:
            return None
        return schemas.TokenData(username=username, role=role, student_id=student_id)
    except JWTError:
        return None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token_data = decode_token(token)
    if token_data is None:
        raise credentials_exception
    user = db.query(models.User).filter(models.User.username == token_data.username).first()
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(current_user: models.User = Depends(get_current_user)) -> models.User:
    return current_user


def require_admin(current_user: models.User = Depends(get_current_active_user)) -> models.User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return current_user


def require_driver(current_user: models.User = Depends(get_current_active_user)) -> models.User:
    if current_user.role != "driver":
        raise HTTPException(status_code=403, detail="Driver role required")
    return current_user


def require_student(current_user: models.User = Depends(get_current_active_user)) -> models.User:
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="Student role required")
    return current_user


def is_drop_window_open(db: Session) -> bool:
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "drop_window_open").first()
    global_open = setting and setting.value.lower() == "true"
    if not global_open:
        return False
    from datetime import datetime
    now = datetime.now().time()
    windows = db.query(models.DropWindow).filter(models.DropWindow.enabled == True).all()
    for w in windows:
        try:
            start = datetime.strptime(w.start_time, "%H:%M").time()
            end = datetime.strptime(w.end_time, "%H:%M").time()
            if start <= now <= end:
                return True
        except ValueError:
            continue
    return False


def is_pickup_window_open(db: Session) -> bool:
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "pickup_window_open").first()
    global_open = setting and setting.value.lower() == "true"
    if not global_open:
        return False
    from datetime import datetime
    now = datetime.now().time()
    windows = db.query(models.PickupWindow).filter(models.PickupWindow.enabled == True).all()
    for w in windows:
        try:
            start = datetime.strptime(w.start_time, "%H:%M").time()
            end = datetime.strptime(w.end_time, "%H:%M").time()
            if start <= now <= end:
                return True
        except ValueError:
            continue
    return False