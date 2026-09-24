from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import models
import schemas
import auth
from datetime import date

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _issue_tokens(user: models.User) -> dict:
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role, "student_id": user.student_id}
    )
    refresh_token = auth.create_refresh_token(data={"sub": user.username})
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer", "role": user.role}


@router.post("/register", response_model=schemas.UserResponse)
def register(user_data: schemas.StudentCreate, db: Session = Depends(auth.get_db)):
    existing = db.query(models.User).filter(
        (models.User.username == user_data.roll_number) | (models.User.email == user_data.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already registered")

    allowed_areas = ["DHA", "Walton", "Ali Park", "Punjab Society", "Cavalry", "Bhata Chowk"]
    if user_data.area not in allowed_areas:
        raise HTTPException(status_code=400, detail=f"Area must be one of {allowed_areas}")

    student = models.Student(
        name=user_data.name,
        email=user_data.email,
        roll_number=user_data.roll_number,
        area=user_data.area,
        pickup_address=user_data.pickup_address,
        drop_address=user_data.drop_address,
        class_slot=user_data.class_slot,
        status="waiting"
    )
    db.add(student)
    db.flush()

    hashed = auth.get_password_hash(user_data.roll_number)
    db_user = models.User(
        username=user_data.roll_number,
        email=user_data.email,
        hashed_password=hashed,
        role="student",
        student_id=student.id
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/student-register", response_model=schemas.UserResponse)
def student_register(student_data: schemas.StudentRegister, db: Session = Depends(auth.get_db)):
    user_data = schemas.StudentCreate(
        name=student_data.name,
        email=student_data.email,
        roll_number=student_data.roll_number,
        area=student_data.area,
        pickup_address=student_data.pickup_address,
        drop_address=student_data.drop_address,
        class_slot=student_data.class_slot,
        status="waiting",
        password=student_data.roll_number
    )
    return register(user_data, db)


@router.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(auth.get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _issue_tokens(user)


@router.post("/refresh", response_model=schemas.Token)
def refresh(request: schemas.RefreshRequest, db: Session = Depends(auth.get_db)):
    """
    Called silently by the app when an access token has expired. Trades
    a still-valid refresh token for a brand new pair of tokens, no
    username or password needed. This is what makes the app stay
    logged in without the user noticing anything.
    """
    username = auth.decode_refresh_token(request.refresh_token)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token, please log in again")
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return _issue_tokens(user)