from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Date, Time, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "admin", "driver", "student"
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
    area = Column(String)  # DHA, Walton, Ali Park, Punjab Society, Cavalry, Bhata Chowk
    pickup_address = Column(String, nullable=True)
    drop_address = Column(String, nullable=True)
    class_slot = Column(String, nullable=True)  # e.g. "Morning", "Afternoon"
    device_token = Column(String, nullable=True)  # FCM token
    status = Column(String, default="waiting")  # waiting, requested, assigned, picked, dropped
    pickup_window_id = Column(Integer, ForeignKey("pickup_windows.id"), nullable=True)
    drop_window_id = Column(Integer, ForeignKey("drop_windows.id"), nullable=True)
    pickup_order = Column(Integer, nullable=True)
    request_date = Column(Date, nullable=True)
    van_id = Column(Integer, ForeignKey("vans.id"), nullable=True)

    user = relationship("User", back_populates="student", foreign_keys="User.student_id")
    pickup_window = relationship("PickupWindow", foreign_keys=[pickup_window_id])
    drop_window = relationship("DropWindow", foreign_keys=[drop_window_id])
    van = relationship("Van", foreign_keys=[van_id])
    assignments = relationship("Assignment", back_populates="student")


class Van(Base):
    __tablename__ = "vans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    capacity = Column(Integer)
    areas = Column(String)  # comma separated areas
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
    start_time = Column(String, nullable=False)  # format "HH:MM"
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