from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from collections import defaultdict
import models
import schemas
import auth
from auth import get_db, require_admin
import logging
from datetime import date

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


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


@router.post("/run-assignment", response_model=schemas.AssignmentResult)
def run_assignment(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    # Get students with status requested
    students = db.query(models.Student).filter(models.Student.status == "requested").all()
    if not students:
        return {"assigned_count": 0, "vans_utilization": []}

    # Group by pickup window, then by area
    by_window_area = defaultdict(lambda: defaultdict(list))
    for s in students:
        by_window_area[s.pickup_window_id][s.area].append(s)

    # Get active vans
    vans = db.query(models.Van).filter(models.Van.is_active == True).all()
    if not vans:
        raise HTTPException(status_code=400, detail="No active vans available")

    # Track van loads
    van_load = {v.id: 0 for v in vans}
    # Map area to vans
    vans_by_area = defaultdict(list)
    for v in vans:
        for a in v.areas.split(","):
            vans_by_area[a.strip()].append(v)

    # Clear previous assignments and reset status for previously assigned students
    db.query(models.Assignment).delete()
    for s in db.query(models.Student).filter(models.Student.status == "assigned").all():
        s.status = "requested"
        s.pickup_order = None
        s.van_id = None
    db.commit()

    assigned_count = 0
    # Process each pickup window separately
    for window_id, areas_dict in by_window_area.items():
        for area, area_students in areas_dict.items():
            available_vans = vans_by_area.get(area, [])
            if not available_vans:
                logger.warning(f"No van serves area {area} for window {window_id}")
                continue
            # Sort vans by current load
            available_vans.sort(key=lambda v: van_load[v.id])
            for student in area_students:
                # Find van with capacity
                best_van = None
                for v in available_vans:
                    if van_load[v.id] < v.capacity:
                        best_van = v
                        break
                if not best_van:
                    break  # no capacity left for this area in this window
                van_load[best_van.id] += 1
                student.status = "assigned"
                student.pickup_order = van_load[best_van.id]
                student.van_id = best_van.id
                assignment = models.Assignment(student_id=student.id, van_id=best_van.id)
                db.add(assignment)
                assigned_count += 1
                # re-sort vans
                available_vans.sort(key=lambda v: van_load[v.id])

    db.commit()

    # Build utilization
    utilization = [
        schemas.VanUtilization(van_name=v.name, used=van_load[v.id], capacity=v.capacity)
        for v in vans
    ]
    return {"assigned_count": assigned_count, "vans_utilization": utilization}


@router.post("/reset-day", response_model=schemas.MessageResponse)
def reset_day(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin)
):
    # Reset all students
    students = db.query(models.Student).all()
    for s in students:
        s.status = "waiting"
        s.pickup_order = None
        s.pickup_window_id = None
        s.drop_window_id = None
        s.request_date = None
        s.van_id = None
    db.query(models.Assignment).delete()
    db.query(models.DailyRoute).delete()
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