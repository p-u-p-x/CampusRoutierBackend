from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
import models
import schemas
import auth
from auth import get_db, require_driver
from datetime import datetime, date
import logging
import math
from firebase_service import send_push

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/driver", tags=["Driver"])

MOVEMENT_THRESHOLD_METERS = 100


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


def _log_event(db: Session, van: models.Van, trip_id: int, event_type: str, student_id: int = None):
    event = models.StopEvent(
        trip_id=trip_id,
        student_id=student_id,
        event_type=event_type,
        latitude=van.current_lat,
        longitude=van.current_lng,
    )
    db.add(event)


def _distance_meters(lat1, lon1, lat2, lon2) -> float:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _window_time_passed(window_start_time: str) -> bool:
    today = date.today()
    hour, minute = map(int, window_start_time.split(":"))
    window_dt = datetime.combine(today, datetime.min.time()).replace(hour=hour, minute=minute)
    return datetime.now() >= window_dt


def _maybe_auto_start_trip(db: Session, van: models.Van, prev_lat, prev_lng, new_lat, new_lng):
    already_in_progress = db.query(models.Trip).filter(
        models.Trip.van_id == van.id,
        models.Trip.status == "in_progress",
    ).first()
    if already_in_progress:
        return

    if prev_lat is None or prev_lng is None:
        return

    moved = _distance_meters(prev_lat, prev_lng, new_lat, new_lng)
    if moved < MOVEMENT_THRESHOLD_METERS:
        return

    today = date.today()
    candidates = db.query(models.Trip).filter(
        models.Trip.van_id == van.id,
        models.Trip.trip_date == today,
        models.Trip.status == "scheduled",
    ).all()

    due_now = []
    for t in candidates:
        window = t.pickup_window if t.trip_type == "pickup" else t.drop_window
        if window and _window_time_passed(window.start_time):
            due_now.append((window.start_time, t))

    if not due_now:
        return

    due_now.sort(key=lambda x: x[0])
    _, trip_to_start = due_now[0]

    trip_to_start.status = "in_progress"
    trip_to_start.started_at = datetime.utcnow()
    _log_event(db, van, trip_to_start.id, "trip_started")
    logger.info(f"Auto-started trip {trip_to_start.id} for van {van.id} after {moved:.0f}m of movement")
    _notify_trip_started(db, trip_to_start)


def _notify_trip_started(db: Session, trip: models.Trip):
    """Pushes 'route started' to every student on this trip."""
    if trip.trip_type == "pickup":
        students = db.query(models.Student).filter(models.Student.pickup_trip_id == trip.id).all()
        title = "Van is on the way"
        body = "Your pickup van has started its route."
    else:
        students = db.query(models.Student).filter(models.Student.drop_trip_id == trip.id).all()
        title = "Drop route started"
        body = "The van has started the drop route. Head to the van if you haven't already."

    for s in students:
        if s.device_token:
            send_push(s.device_token, title, body, data={"trip_id": trip.id, "type": "trip_started"})


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
    van = get_driver_van(current_user.id, db)
    prev_lat, prev_lng = van.current_lat, van.current_lng

    van.current_lat = location.latitude
    van.current_lng = location.longitude
    van.location_updated_at = datetime.utcnow()

    _maybe_auto_start_trip(db, van, prev_lat, prev_lng, location.latitude, location.longitude)

    db.commit()
    return {"message": "Location updated"}


@router.get("/my-trips-today", response_model=list[schemas.TripResponse])
def my_trips_today(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
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

    other_in_progress = db.query(models.Trip).filter(
        models.Trip.van_id == van.id,
        models.Trip.id != trip.id,
        models.Trip.status == "in_progress",
    ).first()
    if other_in_progress:
        raise HTTPException(
            status_code=400,
            detail=f"Finish your current {other_in_progress.trip_type} trip before starting this one"
        )

    trip.status = "in_progress"
    trip.started_at = datetime.utcnow()
    _log_event(db, van, trip.id, "trip_started")
    db.commit()

    _notify_trip_started(db, trip)

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
    _log_event(db, van, trip.id, "trip_completed")
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
    _log_event(db, van, trip.id, "picked", student_id=student.id)
    db.commit()
    logger.info(f"Driver {current_user.id} picked student {student_id}")
    return {"message": "Student picked successfully"}


@router.post("/no-show/{student_id}", response_model=schemas.MessageResponse)
def no_show_student(
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

    student.status = "no_show"
    _log_event(db, van, trip.id, "no_show", student_id=student.id)
    db.commit()
    logger.info(f"Driver {current_user.id} marked student {student_id} as no-show")
    return {"message": "Student marked as no-show"}


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
    _log_event(db, van, trip.id, "dropped", student_id=student.id)
    db.commit()
    logger.info(f"Driver {current_user.id} dropped student {student_id}")
    return {"message": "Student dropped successfully"}


@router.post("/notify-arrival/{trip_id}", response_model=schemas.MessageResponse)
def notify_arrival(
    trip_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_driver)
):
    van = get_driver_van(current_user.id, db)
    trip = get_trip_for_van(trip_id, van.id, db)

    trip.arrived_at = datetime.utcnow()
    _log_event(db, van, trip.id, "arrived")
    db.commit()

    if trip.trip_type == "pickup":
        students = db.query(models.Student).filter(models.Student.pickup_trip_id == trip.id).all()
        title = "Van has arrived"
        body = "The van has reached uni. Come outside if you're heading home."
    else:
        students = db.query(models.Student).filter(models.Student.drop_trip_id == trip.id).all()
        title = "Van has arrived"
        body = "The van has reached uni and is waiting for drop-off riders."

    notified = 0
    for s in students:
        if s.device_token:
            sent = send_push(s.device_token, title, body, data={"trip_id": trip.id, "type": "arrived"})
            if sent:
                notified += 1

    logger.info(f"Arrival notification for trip {trip_id}: notified {notified} of {len(students)} students")
    return {"message": f"Arrival marked, {notified} students notified"}