from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
import models
import schemas
import auth
from auth import get_db, require_driver
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/driver", tags=["Driver"])


def get_driver_van(driver_id: int, db: Session) -> models.Van:
    van = db.query(models.Van).filter(models.Van.driver_id == driver_id).first()
    if not van:
        raise HTTPException(status_code=404, detail="No van assigned")
    return van


def get_trip_for_van(trip_id: int, van_id: int, db: Session) -> models.Trip:
    trip = db.query(models.Trip).filter(
        models.Trip.id == trip_id,
        models.Trip.van_id == van_id,
    ).first()
    if not trip:
        raise HTTPException(status_code=403, detail="That trip does not belong to your van")
    return trip


@router.get("/my-van", response_model=schemas.DriverVanResponse)
def my_van(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    return {"van_id": van.id, "van_name": van.name, "capacity": van.capacity}


@router.post("/update-location", response_model=schemas.MessageResponse)
def update_location(
    location: schemas.LocationUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    """
    Called periodically (every 5-10s) by the driver's phone while the app is
    open, so students can see the van moving on their live map.
    """
    van = get_driver_van(current_user.id, db)
    van.current_lat = location.latitude
    van.current_lng = location.longitude
    van.location_updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Location updated"}


@router.get("/my-trips-today", response_model=list[schemas.TripResponse])
def my_trips_today(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    """
    Everything this driver's van is scheduled to run today, pickup and
    drop, in order. A trip with 0 students is still shown, the driver
    simply has nothing to do on it and can skip starting it.
    """
    van = get_driver_van(current_user.id, db)
    today = date.today()
    trips = db.query(models.Trip).filter(
        models.Trip.van_id == van.id,
        models.Trip.trip_date == today,
    ).all()

    result = []
    for t in trips:
        if t.trip_type == "pickup":
            count = db.query(func.count(models.Student.id)).filter(
                models.Student.pickup_trip_id == t.id
            ).scalar()
            window = t.pickup_window
        else:
            count = db.query(func.count(models.Student.id)).filter(
                models.Student.drop_trip_id == t.id
            ).scalar()
            window = t.drop_window

        result.append({
            "id": t.id,
            "trip_type": t.trip_type,
            "window_start": window.start_time if window else None,
            "window_end": window.end_time if window else None,
            "status": t.status,
            "student_count": count,
            "started_at": t.started_at,
            "arrived_at": t.arrived_at,
        })

    # Order by scheduled start time so the driver sees their day in order
    result.sort(key=lambda r: r["window_start"] or "")
    return result


@router.post("/start-trip/{trip_id}", response_model=schemas.MessageResponse)
def start_trip(
    trip_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    trip = get_trip_for_van(trip_id, van.id, db)
    if trip.status != "scheduled":
        raise HTTPException(status_code=400, detail=f"Trip is already {trip.status}")

    trip.status = "in_progress"
    trip.started_at = datetime.utcnow()
    db.commit()

    # Notification hook point for Stage 3: every student on this trip
    # should get a "route started" push here, once Firebase is wired in.
    logger.info(f"Driver {current_user.id} started trip {trip_id} ({trip.trip_type})")
    return {"message": f"{trip.trip_type.capitalize()} trip started"}


@router.post("/complete-trip/{trip_id}", response_model=schemas.MessageResponse)
def complete_trip(
    trip_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    trip = get_trip_for_van(trip_id, van.id, db)
    if trip.status != "in_progress":
        raise HTTPException(status_code=400, detail=f"Trip is not in progress (currently {trip.status})")

    trip.status = "completed"
    db.commit()
    logger.info(f"Driver {current_user.id} completed trip {trip_id} ({trip.trip_type})")
    return {"message": f"{trip.trip_type.capitalize()} trip marked completed"}


@router.get("/pickup-list/{trip_id}", response_model=list[schemas.DriverTripStudent])
def pickup_list(
    trip_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    trip = get_trip_for_van(trip_id, van.id, db)
    if trip.trip_type != "pickup":
        raise HTTPException(status_code=400, detail="That trip is not a pickup trip")

    students = db.query(models.Student).filter(
        models.Student.pickup_trip_id == trip.id
    ).order_by(models.Student.pickup_order).all()

    return [
        {
            "student_id": s.id,
            "name": s.name,
            "area": s.area,
            "pickup_order": s.pickup_order,
            "status": s.status,
            "pickup_address": s.pickup_address,
            "class_slot": s.class_slot,
        }
        for s in students
    ]


@router.get("/drop-list/{trip_id}", response_model=list[schemas.DriverTripStudent])
def drop_list(
    trip_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    trip = get_trip_for_van(trip_id, van.id, db)
    if trip.trip_type != "drop":
        raise HTTPException(status_code=400, detail="That trip is not a drop trip")

    students = db.query(models.Student).filter(
        models.Student.drop_trip_id == trip.id
    ).all()

    return [
        {
            "student_id": s.id,
            "name": s.name,
            "area": s.area,
            "pickup_order": None,
            "status": s.status,
            "drop_address": s.drop_address,
            "class_slot": s.class_slot,
        }
        for s in students
    ]


@router.post("/pick/{student_id}", response_model=schemas.MessageResponse)
def pick_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student or not student.pickup_trip_id:
        raise HTTPException(status_code=404, detail="Student not found or has no pickup trip")

    trip = db.query(models.Trip).filter(models.Trip.id == student.pickup_trip_id).first()
    if not trip or trip.van_id != van.id:
        raise HTTPException(status_code=403, detail="Student not on your van's trip")
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
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student or not student.drop_trip_id:
        raise HTTPException(status_code=404, detail="Student not found or has no drop trip")

    trip = db.query(models.Trip).filter(models.Trip.id == student.drop_trip_id).first()
    if not trip or trip.van_id != van.id:
        raise HTTPException(status_code=403, detail="Student not on your van's trip")
    if student.status != "picked":
        raise HTTPException(status_code=400, detail=f"Student status is {student.status}")

    student.status = "dropped"
    db.commit()
    logger.info(f"Driver {current_user.id} dropped student {student_id}")
    return {"message": "Student dropped successfully"}


@router.post("/notify-arrival/{trip_id}", response_model=schemas.MessageResponse)
def notify_arrival(
    trip_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    """
    One alert to everyone on this specific trip: 'van has arrived, come
    outside'. Fires once, for the whole trip, not per student.
    """
    van = get_driver_van(current_user.id, db)
    trip = get_trip_for_van(trip_id, van.id, db)

    trip.arrived_at = datetime.utcnow()
    db.commit()

    if trip.trip_type == "pickup":
        students = db.query(models.Student).filter(models.Student.pickup_trip_id == trip.id).all()
    else:
        students = db.query(models.Student).filter(models.Student.drop_trip_id == trip.id).all()

    # Notification hook point for Stage 3: send one push to every student
    # in `students` here, once Firebase is wired in. For now, just logged.
    notified = [s.id for s in students if s.device_token]
    logger.info(f"Arrival notification for trip {trip_id}: would notify students {notified}")
    return {"message": f"Arrival marked, {len(notified)} students would be notified"}