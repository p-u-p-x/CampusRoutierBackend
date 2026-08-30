# services/drop_window_service.py
from sqlalchemy.orm import Session
from datetime import datetime
import models

def is_drop_window_open(db: Session) -> bool:
    """
    Check if any enabled drop window is currently open.
    Returns True if current time is within start_time and end_time of an enabled window.
    """
    now = datetime.now().time()
    windows = db.query(models.DropWindow).filter(models.DropWindow.enabled == True).all()
    for window in windows:
        try:
            start = datetime.strptime(window.start_time, "%H:%M").time()
            end = datetime.strptime(window.end_time, "%H:%M").time()
            if start <= now <= end:
                return True
        except ValueError:
            # Invalid time format; skip this window
            continue
    return False