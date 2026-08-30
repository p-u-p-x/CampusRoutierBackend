from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import models
import schemas
import auth
from auth import get_db, require_driver
from datetime import datetime, date, time
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/driver", tags=["Driver"])


def get_driver_van(driver_id: int, db: Session) -> models.Van:
    van = db.query(models.Van).filter(models.Van.driver_id == driver_id).first()
    if not van:
        raise HTTPException(status_code=404, detail="No van assigned")
    return van


@router.get("/my-van", response_model=schemas.DriverVanResponse)
def my_van(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    return {"van_id": van.id, "van_name": van.name, "capacity": van.capacity}


@router.get("/pickup-list", response_model=list[schemas.DriverPickupStudent])
def pickup_list(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    assignments = db.query(models.Assignment).filter(models.Assignment.van_id == van.id).all()
    student_ids = [a.student_id for a in assignments]
    students = db.query(models.Student).filter(
        models.Student.id.in_(student_ids),
        models.Student.status.in_(["assigned", "picked"])
    ).order_by(models.Student.pickup_order).all()

    result = []
    for s in students:
        result.append({
            "student_id": s.id,
            "name": s.name,
            "area": s.area,
            "pickup_order": s.pickup_order,
            "status": s.status,
            "pickup_window": f"{s.pickup_window.start_time}-{s.pickup_window.end_time}" if s.pickup_window else None,
            "drop_window": f"{s.drop_window.start_time}-{s.drop_window.end_time}" if s.drop_window else None,
            "pickup_address": s.pickup_address,
            "class_slot": s.class_slot,
        })
    return result


@router.post("/pick/{student_id}", response_model=schemas.MessageResponse)
def pick_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    assignment = db.query(models.Assignment).filter(
        models.Assignment.student_id == student_id,
        models.Assignment.van_id == van.id
    ).first()
    if not assignment:
        raise HTTPException(status_code=403, detail="Student not in your van")
    student = assignment.student
    if student.status != "assigned":
        raise HTTPException(status_code=400, detail=f"Student status is {student.status}")
    student.status = "picked"
    db.commit()
    logger.info(f"Driver {current_user.id} picked student {student_id}")
    return {"message": "Student picked successfully"}


@router.post("/drop/{student_id}", response_model=schemas.MessageResponse)
def drop_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    assignment = db.query(models.Assignment).filter(
        models.Assignment.student_id == student_id,
        models.Assignment.van_id == van.id
    ).first()
    if not assignment:
        raise HTTPException(status_code=403, detail="Student not in your van")
    student = assignment.student
    if student.status != "picked":
        raise HTTPException(status_code=400, detail=f"Student status is {student.status}")
    student.status = "dropped"
    db.commit()
    logger.info(f"Driver {current_user.id} dropped student {student_id}")
    return {"message": "Student dropped successfully"}


@router.post("/start-pickup-route", response_model=schemas.MessageResponse)
def start_pickup_route(
    request: schemas.StartPickupRouteRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    today = date.today()
    # Parse time
    try:
        pickup_time = datetime.strptime(request.pickup_start_time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM (24-hour)")
    route = db.query(models.DailyRoute).filter(
        models.DailyRoute.date == today,
        models.DailyRoute.van_id == van.id
    ).first()
    if not route:
        route = models.DailyRoute(
            date=today,
            van_id=van.id,
            driver_id=current_user.id,
            pickup_start_time=pickup_time
        )
        db.add(route)
    else:
        route.pickup_start_time = pickup_time
    db.commit()

    # Send notifications to students (simulate with FCM)
    # For now just log
    logger.info(f"Driver {current_user.id} started pickup route at {pickup_time}")
    return {"message": f"Pickup route started at {pickup_time.strftime('%I:%M %p')}"}


@router.post("/start-drop-route", response_model=schemas.MessageResponse)
def start_drop_route(
    request: schemas.StartDropRouteRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    today = date.today()
    try:
        drop_time = datetime.strptime(request.drop_start_time, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM (24-hour)")
    route = db.query(models.DailyRoute).filter(
        models.DailyRoute.date == today,
        models.DailyRoute.van_id == van.id
    ).first()
    if not route:
        route = models.DailyRoute(
            date=today,
            van_id=van.id,
            driver_id=current_user.id,
            drop_start_time=drop_time
        )
        db.add(route)
    else:
        route.drop_start_time = drop_time
    db.commit()
    logger.info(f"Driver {current_user.id} started drop route at {drop_time}")
    return {"message": f"Drop route started at {drop_time.strftime('%I:%M %p')}"}


@router.post("/notify-arrival/{student_id}", response_model=schemas.MessageResponse)
def notify_arrival(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    assignment = db.query(models.Assignment).filter(
        models.Assignment.student_id == student_id,
        models.Assignment.van_id == van.id
    ).first()
    if not assignment:
        raise HTTPException(status_code=403, detail="Student not in your van")
    student = assignment.student
    if not student.device_token:
        raise HTTPException(status_code=400, detail="Student has no device token")
    # Send FCM notification (stub)
    logger.info(f"Sending arrival notification to student {student_id}")
    return {"message": "Arrival notification sent"}