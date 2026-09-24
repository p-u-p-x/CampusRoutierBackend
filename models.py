from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Date, Time, Float
from sqlalchemy.orm import relationship
from datetime import datetime, date
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="user", foreign_keys=[student_id])
    van = relationship("Van", foreign_keys="Van.driver_id", back_populates="driver", uselist=False)


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    roll_number = Column(String, unique=True, index=True, nullable=False)
    area = Column(String)
    pickup_address = Column(String, nullable=True)
    drop_address = Column(String, nullable=True)
    class_slot = Column(String, nullable=True)
    device_token = Column(String, nullable=True)
    status = Column(String, default="waiting")
    pickup_window_id = Column(Integer, ForeignKey("pickup_windows.id"), nullable=True)
    drop_window_id = Column(Integer, ForeignKey("drop_windows.id"), nullable=True)
    pickup_order = Column(Integer, nullable=True)
    request_date = Column(Date, nullable=True)
    van_id = Column(Integer, ForeignKey("vans.id"), nullable=True)
    pickup_trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True)
    drop_trip_id = Column(Integer, ForeignKey("trips.id"), nullable=True)

    user = relationship("User", back_populates="student", foreign_keys="User.student_id")
    pickup_window = relationship("PickupWindow", foreign_keys=[pickup_window_id])
    drop_window = relationship("DropWindow", foreign_keys=[drop_window_id])
    van = relationship("Van", foreign_keys=[van_id])
    assignments = relationship("Assignment", back_populates="student")
    pickup_trip = relationship("Trip", foreign_keys=[pickup_trip_id])
    drop_trip = relationship("Trip", foreign_keys=[drop_trip_id])


class Van(Base):
    __tablename__ = "vans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    capacity = Column(Integer)
    areas = Column(String)
    is_active = Column(Boolean, default=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    current_lat = Column(Float, nullable=True)
    current_lng = Column(Float, nullable=True)
    location_updated_at = Column(DateTime, nullable=True)

    driver = relationship("User", foreign_keys=[driver_id], back_populates="van")
    assignments = relationship("Assignment", back_populates="van")


class PickupWindow(Base):
    __tablename__ = "pickup_windows"

    id = Column(Integer, primary_key=True, index=True)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)


class DropWindow(Base):
    __tablename__ = "drop_windows"

    id = Column(Integer, primary_key=True, index=True)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    enabled = Column(Boolean, default=True)


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"))
    van_id = Column(Integer, ForeignKey("vans.id"))

    student = relationship("Student", back_populates="assignments")
    van = relationship("Van", back_populates="assignments")


class DailyRoute(Base):
    __tablename__ = "daily_routes"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, default=datetime.utcnow().date)
    pickup_start_time = Column(Time, nullable=True)
    drop_start_time = Column(Time, nullable=True)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    van_id = Column(Integer, ForeignKey("vans.id"), nullable=False)

    driver = relationship("User", foreign_keys=[driver_id])
    van = relationship("Van", foreign_keys=[van_id])


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=True)


class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    van_id = Column(Integer, ForeignKey("vans.id"), nullable=False)
    trip_date = Column(Date, nullable=False, default=date.today)
    trip_type = Column(String, nullable=False)
    pickup_window_id = Column(Integer, ForeignKey("pickup_windows.id"), nullable=True)
    drop_window_id = Column(Integer, ForeignKey("drop_windows.id"), nullable=True)
    status = Column(String, default="scheduled")
    started_at = Column(DateTime, nullable=True)
    arrived_at = Column(DateTime, nullable=True)

    van = relationship("Van", foreign_keys=[van_id])
    pickup_window = relationship("PickupWindow", foreign_keys=[pickup_window_id])
    drop_window = relationship("DropWindow", foreign_keys=[drop_window_id])


class StopEvent(Base):
    __tablename__ = "stop_events"

    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=True)
    event_type = Column(String, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    trip = relationship("Trip", foreign_keys=[trip_id])
    student = relationship("Student", foreign_keys=[student_id])


class RosterEntry(Base):
    """
    The list of roll numbers the admin has actually approved to register.
    A roll number not in here cannot sign up at all. Once used, it's
    locked, so nobody else can ever claim that same roll number.
    """
    __tablename__ = "roster_entries"

    id = Column(Integer, primary_key=True, index=True)
    roll_number = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)  # admin's own reference, optional
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)