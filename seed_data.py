from database import SessionLocal, engine
from models import Base, Student, Van, DropWindow, PickupWindow, User, SystemSetting, DailyRoute
from auth import get_password_hash
from datetime import date, time

Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Clear old data
db.query(Student).delete()
db.query(Van).delete()
db.query(DropWindow).delete()
db.query(PickupWindow).delete()
db.query(User).delete()
db.query(SystemSetting).delete()
db.query(DailyRoute).delete()
db.commit()

# Create pickup windows
pickup_windows = [
    PickupWindow(start_time="08:00", end_time="08:30", enabled=True),
    PickupWindow(start_time="09:00", end_time="09:30", enabled=True),
    PickupWindow(start_time="10:00", end_time="10:30", enabled=True),
]
db.add_all(pickup_windows)
db.commit()

# Create drop windows
drop_windows = [
    DropWindow(start_time="14:00", end_time="14:30", enabled=True),
    DropWindow(start_time="15:30", end_time="16:00", enabled=True),
    DropWindow(start_time="17:00", end_time="17:30", enabled=True),
    DropWindow(start_time="18:30", end_time="19:00", enabled=True),
]
db.add_all(drop_windows)
db.commit()

# Create vans
van1 = Van(name="Van A", capacity=11, areas="DHA,Walton", is_active=True)
van2 = Van(name="Van B", capacity=11, areas="Ali Park,Punjab Society,Cavalry,Bhata Chowk", is_active=True)
db.add_all([van1, van2])
db.commit()

areas = ["DHA", "Walton", "Ali Park", "Punjab Society", "Cavalry", "Bhata Chowk"]

# Create 15 students with associated user accounts
students = []
for i in range(1, 16):
    area = areas[(i-1) % len(areas)]
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
    db.flush()  # get id
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

# Create drivers
driver1 = User(
    username="driver1",
    email="driver1@example.com",
    hashed_password=get_password_hash("driverpass"),
    role="driver"
)
driver2 = User(
    username="driver2",
    email="driver2@example.com",
    hashed_password=get_password_hash("driverpass"),
    role="driver"
)
db.add_all([driver1, driver2])
db.commit()

# Create admin
admin = User(
    username="admin",
    email="admin@example.com",
    hashed_password=get_password_hash("adminpass"),
    role="admin"
)
db.add(admin)
db.commit()

# Assign drivers to vans
van1.driver_id = driver1.id
van2.driver_id = driver2.id
db.commit()

# System settings
settings = [
    SystemSetting(key="drop_window_open", value="true"),
    SystemSetting(key="pickup_window_open", value="true"),
]
db.add_all(settings)
db.commit()

db.close()

print("Clean test data inserted.")