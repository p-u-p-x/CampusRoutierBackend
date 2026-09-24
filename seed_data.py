from database import SessionLocal, engine
from models import Base, Student, Van, DropWindow, PickupWindow, User, SystemSetting, DailyRoute, Assignment, Trip, RosterEntry
from auth import get_password_hash
from datetime import date, time

Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Clear old data: break the cross-references first, then delete
db.query(Assignment).delete()
db.query(DailyRoute).delete()
db.query(Trip).delete()
db.query(Student).update({Student.van_id: None, Student.pickup_trip_id: None, Student.drop_trip_id: None})
db.query(Van).update({Van.driver_id: None})
db.query(User).update({User.student_id: None})
db.commit()

db.query(Student).delete()
db.query(Van).delete()
db.query(DropWindow).delete()
db.query(PickupWindow).delete()
db.query(User).delete()
db.query(SystemSetting).delete()
db.query(RosterEntry).delete()
db.commit()

# Pickup windows: van departs home at start_time, must deliver students
# to campus by end_time, which is when their class starts.
pickup_windows = [
    PickupWindow(start_time="06:30", end_time="08:00", enabled=True),  # for 8:00 class
    PickupWindow(start_time="08:00", end_time="09:30", enabled=True),  # for 9:30 class
    PickupWindow(start_time="09:00", end_time="11:00", enabled=True),  # for 11:00 class
    PickupWindow(start_time="12:00", end_time="14:00", enabled=True),  # for 2:00 class
]
db.add_all(pickup_windows)
db.commit()

# Drop windows: van waits at campus from start_time, picks up whoever's
# ready, and heads home. end_time is when the van needs to be free again,
# either for the next drop trip or, for the 11:00 drop, the day's last
# pickup route at 12:00 - not a hard 15 minute slot like pickup windows.
drop_windows = [
    DropWindow(start_time="11:00", end_time="12:00", enabled=True),  # for 10:45 class end, frees van for 12:00 pickup
    DropWindow(start_time="14:00", end_time="15:30", enabled=True),  # for 1:45 class end
    DropWindow(start_time="15:30", end_time="17:00", enabled=True),  # for 3:15 class end
    DropWindow(start_time="17:00", end_time="18:30", enabled=True),  # for 4:45 class end
    DropWindow(start_time="18:30", end_time="19:30", enabled=True),  # for 6:15 class end, last trip of the day
]
db.add_all(drop_windows)
db.commit()

# Vans — update names/count here if your real fleet differs
vans = [
    Van(name="Van A", capacity=11, areas="DHA,Walton", is_active=True),
    Van(name="Van B", capacity=11, areas="Ali Park,Punjab Society", is_active=True),
    Van(name="Van C", capacity=11, areas="Cavalry,Bhata Chowk", is_active=True),
    Van(name="Van D", capacity=11, areas="DHA,Walton,Ali Park,Punjab Society,Cavalry,Bhata Chowk", is_active=True),
]
db.add_all(vans)
db.commit()

areas = ["DHA", "Walton", "Ali Park", "Punjab Society", "Cavalry", "Bhata Chowk"]

# Create 15 students with associated user accounts.
# These are test accounts created directly, bypassing registration
# entirely, so they don't touch the roster at all - that's expected.
students = []
for i in range(1, 16):
    area = areas[(i - 1) % len(areas)]
    roll = f"STU00{i}"
    student = Student(
        name=f"Student{i}",
        email=f"student{i}@example.com",
        roll_number=roll,
        area=area,
        pickup_address=f"Address {i} Pickup",
        drop_address=f"Address {i} Drop",
        class_slot="Morning" if i % 2 == 0 else "Afternoon",
        status="waiting"
    )
    db.add(student)
    db.flush()
    user = User(
        username=roll,
        email=f"student{i}@example.com",
        hashed_password=get_password_hash(roll),
        role="student",
        student_id=student.id
    )
    db.add(user)
    students.append(student)
db.commit()

# Drivers — one per van; add more if you have 4 real vans
driver1 = User(username="driver1", email="driver1@example.com",
                hashed_password=get_password_hash("driverpass"), role="driver")
driver2 = User(username="driver2", email="driver2@example.com",
                hashed_password=get_password_hash("driverpass"), role="driver")
driver3 = User(username="driver3", email="driver3@example.com",
                hashed_password=get_password_hash("driverpass"), role="driver")
driver4 = User(username="driver4", email="driver4@example.com",
                hashed_password=get_password_hash("driverpass"), role="driver")
db.add_all([driver1, driver2, driver3, driver4])
db.commit()

admin = User(username="admin", email="admin@example.com",
             hashed_password=get_password_hash("adminpass"), role="admin")
db.add(admin)
db.commit()

vans[0].driver_id = driver1.id
vans[1].driver_id = driver2.id
vans[2].driver_id = driver3.id
vans[3].driver_id = driver4.id
db.commit()

settings = [
    SystemSetting(key="drop_window_open", value="true"),
    SystemSetting(key="pickup_window_open", value="true"),
]
db.add_all(settings)
db.commit()

# A few roster entries for testing real self-registration.
# STU001 through STU015 already exist as full accounts above and don't
# need this; these are for testing NEW signups going through the roster.
roster_entries = [
    RosterEntry(roll_number="STU016", name="Test Roster Student 1"),
    RosterEntry(roll_number="STU017", name="Test Roster Student 2"),
]
db.add_all(roster_entries)
db.commit()

# Create today's trips: every active van runs every pickup and drop window
today = date.today()
for van in vans:
    for pw in pickup_windows:
        db.add(Trip(van_id=van.id, trip_date=today, trip_type="pickup", pickup_window_id=pw.id))
    for dw in drop_windows:
        db.add(Trip(van_id=van.id, trip_date=today, trip_type="drop", drop_window_id=dw.id))
db.commit()

db.close()

print("Clean test data inserted, with real schedule windows, roster entries, and today's trips.")