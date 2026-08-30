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
    """
    Polled every 5-10s by the student's app (once they have a van assigned)
    to show the van's last-reported position on the live map.
    """
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

    # Check if already requested today
    today = date.today()
    if student.request_date == today and student.status != "waiting":
        raise HTTPException(status_code=400, detail="You have already requested transport today")

    # Validate pickup window
    pickup_window = db.query(models.PickupWindow).filter(
        models.PickupWindow.id == request_data.pickup_window_id,
        models.PickupWindow.enabled == True
    ).first()
    if not pickup_window:
        raise HTTPException(status_code=400, detail="Invalid or disabled pickup window")

    # Validate drop window
    drop_window = db.query(models.DropWindow).filter(
        models.DropWindow.id == request_data.drop_window_id,
        models.DropWindow.enabled == True
    ).first()
    if not drop_window:
        raise HTTPException(status_code=400, detail="Invalid or disabled drop window")

    # Update student
    student.pickup_window_id = request_data.pickup_window_id
    student.drop_window_id = request_data.drop_window_id
    student.status = "requested"
    student.request_date = today
    db.commit()

    logger.info(f"Student {student.id} requested transport")
    return {"message": "Transport request submitted successfully"}


@router.get("/my-status", response_model=schemas.StudentStatusResponse)
def my_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_student)
):
    student = db.query(models.Student).filter(models.Student.id == current_user.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Get van info
    van = None
    if student.van_id:
        van = db.query(models.Van).filter(models.Van.id == student.van_id).first()

    # Format windows
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
    if not student.van_id:
        return {"pickup_start_time": None, "drop_start_time": None}
    today = date.today()
    route = db.query(models.DailyRoute).filter(
        models.DailyRoute.date == today,
        models.DailyRoute.van_id == student.van_id
    ).first()
    if not route:
        return {"pickup_start_time": None, "drop_start_time": None}
    # Format times to 12-hour
    pickup_str = None
    if route.pickup_start_time:
        pickup_str = route.pickup_start_time.strftime("%I:%M %p").lstrip("0")
    drop_str = None
    if route.drop_start_time:
        drop_str = route.drop_start_time.strftime("%I:%M %p").lstrip("0")
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