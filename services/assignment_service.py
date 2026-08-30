# services/assignment_service.py
import logging
from sqlalchemy.orm import Session
from collections import defaultdict
from models import Student, Van, Assignment

logger = logging.getLogger(__name__)

def run_assignment(db: Session):
    """
    Smart balanced assignment:
    1. Priority: requested students first, then waiting
    2. Group by area
    3. For each area, assign to vans with lowest current load
    4. Respect capacity, spread load evenly
    """
    # Get students in priority order
    requested = db.query(Student).filter(Student.status == "requested").all()
    waiting = db.query(Student).filter(Student.status == "waiting").all()
    students = requested + waiting  # requested first
    if not students:
        logger.info("No students to assign.")
        return {"assigned_count": 0, "vans_utilization": []}

    # Group by area
    students_by_area = defaultdict(list)
    for student in students:
        students_by_area[student.area].append(student)

    # Get active vans
    vans = db.query(Van).filter(Van.is_active == True).all()
    if not vans:
        logger.error("No active vans available.")
        raise Exception("No active vans available")

    # Prepare van load tracking
    van_load = {van.id: 0 for van in vans}
    # Map area to list of vans serving it
    vans_by_area = defaultdict(list)
    for van in vans:
        areas = [area.strip() for area in van.areas.split(",")]
        for area in areas:
            vans_by_area[area].append(van)

    # Clear previous assignments and reset pickup_order
    db.query(Assignment).delete()
    for student in db.query(Student).filter(Student.status == "assigned").all():
        student.status = "waiting"
        student.pickup_order = None
    db.commit()

    assigned_count = 0
    # For each area, assign students to vans with lowest load
    for area, area_students in students_by_area.items():
        available_vans = vans_by_area.get(area, [])
        if not available_vans:
            logger.warning(f"No van serves area {area}. Students left unassigned.")
            continue

        # Sort vans by current load
        area_vans = sorted(available_vans, key=lambda v: van_load[v.id])
        student_idx = 0
        for student in area_students:
            # Find best van (lowest load, not full)
            best_van = None
            for van in area_vans:
                if van_load[van.id] < van.capacity:
                    best_van = van
                    break
            if not best_van:
                logger.warning(f"All vans for area {area} are full. Remaining students unassigned.")
                break

            # Assign student to best_van
            van_load[best_van.id] += 1
            student.status = "assigned"
            student.pickup_order = van_load[best_van.id]  # order = load after assignment
            assignment = Assignment(student_id=student.id, van_id=best_van.id)
            db.add(assignment)
            assigned_count += 1
            logger.info(f"Assigned student {student.id} to van {best_van.id} (load {van_load[best_van.id]})")

            # Re-sort vans by load after assignment
            area_vans.sort(key=lambda v: van_load[v.id])

    db.commit()

    # Build utilization report
    utilization = []
    for van in vans:
        utilization.append({
            "van_id": van.id,
            "van_name": van.name,
            "used": van_load[van.id],
            "capacity": van.capacity
        })

    logger.info(f"Assignment completed, {assigned_count} students assigned.")
    return {
        "assigned_count": assigned_count,
        "vans_utilization": utilization
    }