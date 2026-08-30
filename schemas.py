from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, date, time


# ---------- User ----------
class UserBase(BaseModel):
    username: str
    email: EmailStr
    role: str
    student_id: Optional[int] = None


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(UserBase):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class UserMinimal(BaseModel):
    id: int
    username: str
    role: str

    model_config = {"from_attributes": True}


# ---------- Token ----------
class Token(BaseModel):
    access_token: str
    token_type: str
    role: str


class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None
    student_id: Optional[int] = None


# ---------- Student ----------
class StudentBase(BaseModel):
    name: str
    email: EmailStr
    roll_number: str
    area: str
    pickup_address: Optional[str] = None
    drop_address: Optional[str] = None
    class_slot: Optional[str] = None
    status: str = "waiting"


class StudentCreate(StudentBase):
    password: str  # for registration, will be set to roll_number


class StudentRegister(BaseModel):
    name: str
    email: EmailStr
    roll_number: str
    area: str
    pickup_address: str
    drop_address: str
    class_slot: str


class StudentResponse(StudentBase):
    id: int
    pickup_window_id: Optional[int] = None
    drop_window_id: Optional[int] = None
    pickup_order: Optional[int] = None
    request_date: Optional[date] = None
    van_id: Optional[int] = None
    device_token: Optional[str] = None

    model_config = {"from_attributes": True}


class StudentStatusResponse(BaseModel):
    status: str
    area: str
    van_id: Optional[int] = None
    van_number: Optional[str] = None
    driver_name: Optional[str] = None
    pickup_order: Optional[int] = None
    pickup_window: Optional[str] = None
    drop_window: Optional[str] = None
    pickup_address: Optional[str] = None
    drop_address: Optional[str] = None
    class_slot: Optional[str] = None

    model_config = {"from_attributes": True}


class StudentRequest(BaseModel):
    pickup_window_id: int
    drop_window_id: int


class UpdateAddressRequest(BaseModel):
    pickup_address: str
    drop_address: str


# ---------- Van ----------
class VanBase(BaseModel):
    name: str
    capacity: int
    areas: str
    is_active: bool = True
    driver_id: Optional[int] = None


class VanResponse(VanBase):
    id: int

    model_config = {"from_attributes": True}


# ---------- Assignment ----------
class AssignmentBase(BaseModel):
    student_id: int
    van_id: int


class AssignmentResponse(AssignmentBase):
    id: int

    model_config = {"from_attributes": True}


# ---------- Windows ----------
class PickupWindowBase(BaseModel):
    start_time: str
    end_time: str
    enabled: bool = True


class PickupWindowResponse(PickupWindowBase):
    id: int

    model_config = {"from_attributes": True}


class DropWindowBase(BaseModel):
    start_time: str
    end_time: str
    enabled: bool = True


class DropWindowResponse(DropWindowBase):
    id: int

    model_config = {"from_attributes": True}


# ---------- Dashboard ----------
class DashboardResponse(BaseModel):
    total_students: int
    waiting: int
    requested: int
    assigned: int
    picked: int
    dropped: int


# ---------- Generic Message ----------
class MessageResponse(BaseModel):
    message: str


# ---------- Driver ----------
class DriverVanResponse(BaseModel):
    van_id: int
    van_name: str
    capacity: int


class DriverPickupStudent(BaseModel):
    student_id: int
    name: str
    area: str
    pickup_order: int
    status: str
    pickup_window: Optional[str] = None
    drop_window: Optional[str] = None
    pickup_address: Optional[str] = None
    class_slot: Optional[str] = None


class StartPickupRouteRequest(BaseModel):
    pickup_start_time: str  # "HH:MM" 24-hour


class StartDropRouteRequest(BaseModel):
    drop_start_time: str


# ---------- Daily Route ----------
class DailyRouteResponse(BaseModel):
    pickup_start_time: Optional[str] = None  # formatted as "h:mm AM/PM"
    drop_start_time: Optional[str] = None


# ---------- Assignment Result ----------
class VanUtilization(BaseModel):
    van_name: str
    used: int
    capacity: int


class AssignmentResult(BaseModel):
    assigned_count: int
    vans_utilization: List[VanUtilization]