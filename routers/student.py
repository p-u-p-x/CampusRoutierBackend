from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import models
import schemas
import auth
from auth import get_db, require_student
from datetime import date, datetime, timedelta
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/student", tags=["Student"])


def _format_12h(time_str: str) -> str:
    hour, minute = map(int, time_str.split(":"))
    period = "AM" if hour < 12 else "PM"
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12
    return f"{display_hour}:{minute:02d} {period}"


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


def _window_has_passed_today(window_start_time: str) -> bool:
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

    target = date.today() if request_data.target_date == "today" else date.today() + timedelta(days=1)

    # A fresh day's plan: if this request is for a different date than
    # whatever the student currently has on file, start clean for that
    # new date. Never touches an already-running assignment for the
    # date that's still active.
    if student.request_date != target:
        student.pickup_window_id = None
        student.drop_window_id = None
        student.pickup_trip_id = None
        student.drop_trip_id = None
        student.van_id = None
        student.pickup_order = None
        if student.status not in ("picked", "dropped"):
            student.status = "waiting"

    confirmed_parts = []

    if request_data.pickup_window_id is not None:
        # Changing a side that's already assigned to a real van is
        # allowed, as long as that trip hasn't actually started yet.
        # Once a driver taps Start Trip, the van may already be en
        # route expecting this student, so it locks.
        if student.pickup_trip_id is not None and student.request_date == target:
            current_trip = db.query(models.Trip).filter(models.Trip.id == student.pickup_trip_id).first()
            if current_trip and current_trip.status != "scheduled":
                raise HTTPException(
                    status_code=400,
                    detail="Your pickup route has already started, it's too late to change this one"
                )
            # Free up the old seat, this side goes back to being requested
            student.pickup_trip_id = None
            student.pickup_order = None
            if student.drop_trip_id is None:
                student.van_id = None  # only clear the shown van if drop isn't holding it too

        pickup_window = db.query(models.PickupWindow).filter(
            models.PickupWindow.id == request_data.pickup_window_id,
            models.PickupWindow.enabled == True
        ).first()
        if not pickup_window:
            raise HTTPException(status_code=400, detail="Invalid or disabled pickup window")
        if target == date.today() and _window_has_passed_today(pickup_window.start_time):
            raise HTTPException(status_code=400, detail="That pickup time has already started, choose a later one or select tomorrow")

        student.pickup_window_id = request_data.pickup_window_id
        confirmed_parts.append("pickup")

    if request_data.drop_window_id is not None:
        if student.drop_trip_id is not None and student.request_date == target:
            current_trip = db.query(models.Trip).filter(models.Trip.id == student.drop_trip_id).first()
            if current_trip and current_trip.status != "scheduled":
                raise HTTPException(
                    status_code=400,
                    detail="Your drop route has already started, it's too late to change this one"
                )
            student.drop_trip_id = None

        drop_window = db.query(models.DropWindow).filter(
            models.DropWindow.id == request_data.drop_window_id,
            models.DropWindow.enabled == True
        ).first()
        if not drop_window:
            raise HTTPException(status_code=400, detail="Invalid or disabled drop window")
        if target == date.today() and _window_has_passed_today(drop_window.start_time):
            raise HTTPException(status_code=400, detail="That drop time has already started, choose a later one or select tomorrow")

        student.drop_window_id = request_data.drop_window_id
        confirmed_parts.append("drop")

    # If either side just got freed up above, the overall status needs
    # to reflect that it's pending again, not still "assigned".
    if student.status == "waiting" or student.status == "assigned":
        student.status = "requested"
    student.request_date = target
    db.commit()

    day_label = "today" if target == date.today() else "tomorrow"
    logger.info(f"Student {student.id} requested {', '.join(confirmed_parts)} for {day_label}")
    return {"message": f"{' and '.join(confirmed_parts).capitalize()} request updated for {day_label}"}


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
        pickup_window_str = f"{_format_12h(student.pickup_window.start_time)} - {_format_12h(student.pickup_window.end_time)}"
    drop_window_str = None
    if student.drop_window:
        drop_window_str = f"{_format_12h(student.drop_window.start_time)} - {_format_12h(student.drop_window.end_time)}"

    return {
        "status": student.status,
        "area": student.area,
        "name": student.name,
        "van_id": student.van_id,
        "van_number": van.name if van else None,
        "driver_name": van.driver.username if van and van.driver else None,
        "pickup_order": student.pickup_order,
        "pickup_window": pickup_window_str,
        "drop_window": drop_window_str,
        "pickup_address": student.pickup_address,
        "drop_address": student.drop_address,
        "class_slot": student.class_slot,
        "request_date": student.request_date,
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
        pickup_str = _format_12h(student.pickup_trip.pickup_window.start_time)
    drop_str = None
    if student.drop_trip and student.drop_trip.drop_window:
        drop_str = _format_12h(student.drop_trip.drop_window.start_time)

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