from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import models
import schemas
import auth
from auth import get_db, require_student
from datetime import date, datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/student", tags=["Student"])


@router.get("/van-location", response_model=schemas.VanLocationResponse)
def van_location(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_student)
):
    student = db.query(models.Student).filter(models.Student.id == current_user.student_id).first()
    if not student or not student.van_id:
        raise HTTPException(status_code=404, detail="No van assigned yet")
    van = db.query(models.Van).filter(models.Van.id == student.van_id).first()
    if not van:
        raise HTTPException(status_code=404, detail="Van not found")
    return {
        "van_id": van.id,
        "latitude": van.current_lat,
        "longitude": van.current_lng,
        "updated_at": van.location_updated_at,
    }


@router.get("/pickup-windows", response_model=list[schemas.PickupWindowResponse])
def get_pickup_windows(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_student)
):
    windows = db.query(models.PickupWindow).filter(models.PickupWindow.enabled == True).all()
    return windows


@router.get("/drop-windows", response_model=list[schemas.DropWindowResponse])
def get_drop_windows(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_student)
):
    windows = db.query(models.DropWindow).filter(models.DropWindow.enabled == True).all()
    return windows


def _window_has_passed(window_start_time: str) -> bool:
    """
    A window's cutoff is its own start time, today.
    NOTE: this compares against the server's local clock. Once deployed,
    this needs to compare against Pakistan time specifically, flagged
    for Stage 5 (deployment) so it isn't silently wrong once hosted.
    """
    today = date.today()
    hour, minute = map(int, window_start_time.split(":"))
    window_dt = datetime.combine(today, datetime.min.time()).replace(hour=hour, minute=minute)
    return datetime.now() >= window_dt


@router.post("/request_transport", response_model=schemas.MessageResponse)
def request_transport(
    request_data: schemas.StudentRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_student)
):
    student_id = current_user.student_id
    if student_id is None:
        raise HTTPException(status_code=400, detail="User is not linked to a student")

    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    today = date.today()
    if student.request_date == today and student.status != "waiting":
        raise HTTPException(status_code=400, detail="You have already requested transport today")

    pickup_window = db.query(models.PickupWindow).filter(
        models.PickupWindow.id == request_data.pickup_window_id,
        models.PickupWindow.enabled == True
    ).first()
    if not pickup_window:
        raise HTTPException(status_code=400, detail="Invalid or disabled pickup window")
    if _window_has_passed(pickup_window.start_time):
        raise HTTPException(status_code=400, detail="That pickup time has already started, choose a later one")

    drop_window = db.query(models.DropWindow).filter(
        models.DropWindow.id == request_data.drop_window_id,
        models.DropWindow.enabled == True
    ).first()
    if not drop_window:
        raise HTTPException(status_code=400, detail="Invalid or disabled drop window")
    if _window_has_passed(drop_window.start_time):
        raise HTTPException(status_code=400, detail="That drop time has already started, choose a later one")

    # Just record what the student wants. The admin's automatic
    # assignment step (Stage 2c) is what actually puts them on a van.
    student.pickup_window_id = request_data.pickup_window_id
    student.drop_window_id = request_data.drop_window_id
    student.pickup_trip_id = None
    student.drop_trip_id = None
    student.van_id = None
    student.status = "requested"
    student.request_date = today
    db.commit()

    logger.info(f"Student {student.id} requested pickup window {pickup_window.id}, drop window {drop_window.id}")
    return {"message": "Transport request submitted successfully"}


@router.get("/my-status", response_model=schemas.StudentStatusResponse)
def my_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_student)
):
    student = db.query(models.Student).filter(models.Student.id == current_user.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    van = None
    if student.van_id:
        van = db.query(models.Van).filter(models.Van.id == student.van_id).first()

    pickup_window_str = None
    if student.pickup_window:
        pickup_window_str = f"{student.pickup_window.start_time}-{student.pickup_window.end_time}"
    drop_window_str = None
    if student.drop_window:
        drop_window_str = f"{student.drop_window.start_time}-{student.drop_window.end_time}"

    return {
        "status": student.status,
        "area": student.area,
        "van_id": student.van_id,
        "van_number": van.name if van else None,
        "driver_name": van.driver.username if van and van.driver else None,
        "pickup_order": student.pickup_order,
        "pickup_window": pickup_window_str,
        "drop_window": drop_window_str,
        "pickup_address": student.pickup_address,
        "drop_address": student.drop_address,
        "class_slot": student.class_slot,
    }


@router.post("/update-address", response_model=schemas.MessageResponse)
def update_address(
    address_data: schemas.UpdateAddressRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_student)
):
    student = db.query(models.Student).filter(models.Student.id == current_user.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    student.pickup_address = address_data.pickup_address
    student.drop_address = address_data.drop_address
    db.commit()
    return {"message": "Address updated successfully"}


@router.get("/today-route", response_model=schemas.DailyRouteResponse)
def today_route(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_student)
):
    student = db.query(models.Student).filter(models.Student.id == current_user.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    pickup_str = None
    if student.pickup_trip and student.pickup_trip.pickup_window:
        pickup_str = student.pickup_trip.pickup_window.start_time
    drop_str = None
    if student.drop_trip and student.drop_trip.drop_window:
        drop_str = student.drop_trip.drop_window.start_time

    return {"pickup_start_time": pickup_str, "drop_start_time": drop_str}


@router.post("/save-device-token", response_model=schemas.MessageResponse)
def save_device_token(
    token: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_student)
):
    student = db.query(models.Student).filter(models.Student.id == current_user.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    student.device_token = token
    db.commit()
    return {"message": "Device token saved"}