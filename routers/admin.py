from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from collections import defaultdict
import models
import schemas
import auth
from auth import get_db, require_admin
import logging
from datetime import date

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


def _ensure_todays_trips(db: Session):
    """
    Makes sure every active van has a trip row for every enabled window,
    for today. This is what makes trips 'happen automatically': nobody
    has to manually create them, they just exist whenever needed. A trip
    that ends up with 0 students is simply never started by its driver,
    so it costs nothing to have on the books.
    """
    today = date.today()
    vans = db.query(models.Van).filter(models.Van.is_active == True).all()
    pickup_windows = db.query(models.PickupWindow).filter(models.PickupWindow.enabled == True).all()
    drop_windows = db.query(models.DropWindow).filter(models.DropWindow.enabled == True).all()

    existing = db.query(models.Trip).filter(models.Trip.trip_date == today).all()
    existing_keys = {
        (t.van_id, t.trip_type, t.pickup_window_id, t.drop_window_id) for t in existing
    }

    created_any = False
    for van in vans:
        for pw in pickup_windows:
            key = (van.id, "pickup", pw.id, None)
            if key not in existing_keys:
                db.add(models.Trip(van_id=van.id, trip_date=today, trip_type="pickup", pickup_window_id=pw.id))
                created_any = True
        for dw in drop_windows:
            key = (van.id, "drop", None, dw.id)
            if key not in existing_keys:
                db.add(models.Trip(van_id=van.id, trip_date=today, trip_type="drop", drop_window_id=dw.id))
                created_any = True
    if created_any:
        db.commit()


@router.get("/dashboard", response_model=schemas.DashboardResponse)
def admin_dashboard(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    total = db.query(models.Student).count()
    waiting = db.query(models.Student).filter(models.Student.status == "waiting").count()
    requested = db.query(models.Student).filter(models.Student.status == "requested").count()
    assigned = db.query(models.Student).filter(models.Student.status == "assigned").count()
    picked = db.query(models.Student).filter(models.Student.status == "picked").count()
    dropped = db.query(models.Student).filter(models.Student.status == "dropped").count()
    return {
        "total_students": total,
        "waiting": waiting,
        "requested": requested,
        "assigned": assigned,
        "picked": picked,
        "dropped": dropped,
    }


def _assign_side(db: Session, trip_type: str):
    """
    Handles either the pickup side or the drop side of assignment.
    For every window of this type that has requested students, groups
    those students by area, and fills them into whichever of today's
    trips for that window belong to a van serving that area — never
    exceeding that trip's own 11 seat capacity, and never touching a
    student who already has a trip on this side (safe to re-run).
    """
    today = date.today()
    trip_id_field = models.Student.pickup_trip_id if trip_type == "pickup" else models.Student.drop_trip_id
    window_id_field = models.Student.pickup_window_id if trip_type == "pickup" else models.Student.drop_window_id
    trip_window_filter_field = models.Trip.pickup_window_id if trip_type == "pickup" else models.Trip.drop_window_id

    students = db.query(models.Student).filter(
        models.Student.status == "requested",
        models.Student.request_date == today,
        trip_id_field.is_(None),
    ).all()

    by_window_area = defaultdict(lambda: defaultdict(list))
    for s in students:
        window_id = s.pickup_window_id if trip_type == "pickup" else s.drop_window_id
        if window_id:
            by_window_area[window_id][s.area].append(s)

    assigned_count = 0

    for window_id, areas_dict in by_window_area.items():
        trips_this_window = db.query(models.Trip).filter(
            models.Trip.trip_date == today,
            models.Trip.trip_type == trip_type,
            trip_window_filter_field == window_id,
        ).all()

        # current occupancy per trip = students already using that trip
        trip_load = {}
        for trip in trips_this_window:
            trip_load[trip.id] = db.query(func.count(models.Student.id)).filter(
                trip_id_field == trip.id
            ).scalar()

        for area, area_students in areas_dict.items():
            area_trips = [t for t in trips_this_window if area.strip() in [a.strip() for a in t.van.areas.split(",")]]
            if not area_trips:
                logger.warning(f"No van serves area {area} for {trip_type} window {window_id}")
                continue
            area_trips.sort(key=lambda t: trip_load[t.id])

            for student in area_students:
                best_trip = None
                for t in area_trips:
                    if trip_load[t.id] < t.van.capacity:
                        best_trip = t
                        break
                if not best_trip:
                    break  # no capacity left for this area in this window

                trip_load[best_trip.id] += 1
                if trip_type == "pickup":
                    student.pickup_trip_id = best_trip.id
                    student.van_id = best_trip.van_id
                    student.pickup_order = trip_load[best_trip.id]
                else:
                    student.drop_trip_id = best_trip.id

                assigned_count += 1
                area_trips.sort(key=lambda t: trip_load[t.id])

    return assigned_count


@router.post("/run-assignment", response_model=schemas.AssignmentResult)
def run_assignment(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    today = date.today()
    _apply_weekly_defaults(db, today)
    _ensure_todays_trips(db)

    pickup_assigned = _assign_side(db, "pickup")
    db.commit()
    drop_assigned = _assign_side(db, "drop")
    db.commit()

    # A student is fully "assigned" only once they have both a pickup
    # trip and a drop trip. Otherwise they stay "requested" so the
    # admin can see who's still waiting on capacity.
    today = date.today()
    students = db.query(models.Student).filter(
        models.Student.status == "requested",
        models.Student.request_date == today,
    ).all()
    fully_assigned = 0
    for s in students:
        if s.pickup_trip_id and s.drop_trip_id:
            s.status = "assigned"
            fully_assigned += 1
    db.commit()

    # Utilization, per van, across today's trips of both types
    today_trips = db.query(models.Trip).filter(models.Trip.trip_date == today).all()
    van_used = defaultdict(int)
    for trip in today_trips:
        count = db.query(func.count(models.Student.id)).filter(
            (models.Student.pickup_trip_id == trip.id) | (models.Student.drop_trip_id == trip.id)
        ).scalar()
        van_used[trip.van_id] += count

    vans = db.query(models.Van).filter(models.Van.is_active == True).all()
    utilization = [
        schemas.VanUtilization(van_name=v.name, used=van_used[v.id], capacity=v.capacity)
        for v in vans
    ]

    logger.info(f"Assignment run: {pickup_assigned} pickup, {drop_assigned} drop, {fully_assigned} fully assigned")
    return {"assigned_count": fully_assigned, "vans_utilization": utilization}


@router.post("/reset-day", response_model=schemas.MessageResponse)
def reset_day(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    today = date.today()
    students = db.query(models.Student).all()
    for s in students:
        s.status = "waiting"
        s.pickup_order = None
        s.pickup_window_id = None
        s.drop_window_id = None
        s.pickup_trip_id = None
        s.drop_trip_id = None
        s.request_date = None
        s.van_id = None
    db.query(models.Assignment).delete()
    db.query(models.DailyRoute).delete()
    db.query(models.Trip).filter(models.Trip.trip_date == today).delete()
    db.commit()
    logger.info(f"Admin {current_user.id} reset day")
    return {"message": "Day reset complete"}


@router.get("/drop-window-status", response_model=dict)
def drop_window_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "drop_window_open").first()
    if not setting:
        setting = models.SystemSetting(key="drop_window_open", value="true")
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return {"open": setting.value.lower() == "true"}


@router.post("/toggle-drop-window", response_model=dict)
def toggle_drop_window(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "drop_window_open").first()
    if not setting:
        setting = models.SystemSetting(key="drop_window_open", value="false")
        db.add(setting)
        db.commit()
        db.refresh(setting)
    new_value = "false" if setting.value.lower() == "true" else "true"
    setting.value = new_value
    db.commit()
    return {"open": new_value.lower() == "true"}


@router.get("/pickup-window-status", response_model=dict)
def pickup_window_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "pickup_window_open").first()
    if not setting:
        setting = models.SystemSetting(key="pickup_window_open", value="true")
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return {"open": setting.value.lower() == "true"}


@router.post("/toggle-pickup-window", response_model=dict)
def toggle_pickup_window(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == "pickup_window_open").first()
    if not setting:
        setting = models.SystemSetting(key="pickup_window_open", value="false")
        db.add(setting)
        db.commit()
        db.refresh(setting)
    new_value = "false" if setting.value.lower() == "true" else "true"
    setting.value = new_value
    db.commit()
    return {"open": new_value.lower() == "true"}

@router.post("/roster/add", response_model=schemas.RosterEntryResponse)
def add_to_roster(
    entry: schemas.RosterEntryAdd,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    existing = db.query(models.RosterEntry).filter(models.RosterEntry.roll_number == entry.roll_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="That roll number is already on the roster")
    roster_entry = models.RosterEntry(roll_number=entry.roll_number, name=entry.name)
    db.add(roster_entry)
    db.commit()
    db.refresh(roster_entry)
    return roster_entry


@router.post("/roster/bulk", response_model=list[schemas.RosterEntryResponse])
def add_to_roster_bulk(
    payload: schemas.RosterBulkAdd,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    added = []
    for entry in payload.entries:
        existing = db.query(models.RosterEntry).filter(models.RosterEntry.roll_number == entry.roll_number).first()
        if existing:
            continue  # skip ones already on the roster, don't fail the whole batch
        roster_entry = models.RosterEntry(roll_number=entry.roll_number, name=entry.name)
        db.add(roster_entry)
        added.append(roster_entry)
    db.commit()
    for r in added:
        db.refresh(r)
    return added

def _apply_weekly_defaults(db: Session, target_date: date):
    """
    For any student who has a saved weekly default for target_date's
    weekday, and who hasn't already made an explicit request for that
    exact date, pulls their default in automatically. An explicit
    request always wins - this only fills in students who did nothing.
    """
    day_name = target_date.strftime("%A")  # "Monday", "Tuesday", ...
    defaults = db.query(models.WeeklyDefault).filter(models.WeeklyDefault.day_of_week == day_name).all()

    applied = 0
    for default in defaults:
        student = db.query(models.Student).filter(models.Student.id == default.student_id).first()
        if not student:
            continue
        # Skip anyone who's already explicitly planned this exact date
        if student.request_date == target_date:
            continue

        if default.pickup_window_id:
            student.pickup_window_id = default.pickup_window_id
        if default.drop_window_id:
            student.drop_window_id = default.drop_window_id
        student.pickup_trip_id = None
        student.drop_trip_id = None
        student.van_id = None
        student.pickup_order = None
        student.status = "requested"
        student.request_date = target_date
        applied += 1

    if applied:
        db.commit()
        logger.info(f"Applied {applied} weekly defaults for {day_name} ({target_date})")

@router.get("/roster", response_model=list[schemas.RosterEntryResponse])
def get_roster(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    return db.query(models.RosterEntry).all()

@router.post("/assign-driver", response_model=schemas.VanResponse)
def assign_driver(
    van_id: int,
    driver_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    van = db.query(models.Van).filter(models.Van.id == van_id).first()
    if not van:
        raise HTTPException(status_code=404, detail="Van not found")
    driver = db.query(models.User).filter(models.User.id == driver_id, models.User.role == "driver").first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    van.driver_id = driver.id
    db.commit()
    db.refresh(van)
    logger.info(f"Admin {current_user.id} assigned driver {driver_id} to van {van_id}")
    return van