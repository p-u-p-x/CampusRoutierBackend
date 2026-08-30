from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import models
import schemas
import auth
from datetime import date

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=schemas.UserResponse)
def register(user_data: schemas.StudentCreate, db: Session = Depends(auth.get_db)):
    # Check if username or email exists
    existing = db.query(models.User).filter(
        (models.User.username == user_data.username) | (models.User.email == user_data.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already registered")

    # Validate area
    allowed_areas = ["DHA", "Walton", "Ali Park", "Punjab Society", "Cavalry", "Bhata Chowk"]
    if user_data.area not in allowed_areas:
        raise HTTPException(status_code=400, detail=f"Area must be one of {allowed_areas}")

    # Create student record
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
    db.flush()  # get student.id

    # Create user record with password = roll_number
    hashed = auth.get_password_hash(user_data.roll_number)  # use roll_number as password
    db_user = models.User(
        username=user_data.roll_number,  # username = roll_number
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
    # Convert to StudentCreate
    user_data = schemas.StudentCreate(
        name=student_data.name,
        email=student_data.email,
        roll_number=student_data.roll_number,
        area=student_data.area,
        pickup_address=student_data.pickup_address,
        drop_address=student_data.drop_address,
        class_slot=student_data.class_slot,
        status="waiting",
        password=student_data.roll_number  # password is roll_number
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
    access_token = auth.create_access_token(
        data={"sub": user.username, "role": user.role, "student_id": user.student_id}
    )
    return {"access_token": access_token, "token_type": "bearer", "role": user.role}