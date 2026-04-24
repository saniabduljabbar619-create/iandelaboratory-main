from sqlalchemy.orm import Session
from app.models.notification_model import Notification
import requests
import os

class NotificationService:

    @staticmethod
    def create(
        db: Session,
        type: str,
        title: str,
        message: str,
        reference_type: str = None,
        reference_id: int = None
    ) -> Notification:
        notification = Notification(
            type=type,
            title=title,
            message=message,
            reference_type=reference_type,
            reference_id=reference_id
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        return notification

    @staticmethod
    def list_recent(db: Session, limit: int = 20):
        return (
            db.query(Notification)
            .order_by(Notification.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def unread_count(db: Session) -> int:
        return (
            db.query(Notification)
            .filter(Notification.is_read == False)
            .count()
        )

    @staticmethod
    def mark_read(db: Session, notification_id: int):
        notification = db.query(Notification).filter(Notification.id == notification_id).first()
        if notification:
            notification.is_read = True
            db.commit()
        return notification

    # ==========================================================
    # SENDCHAMP SMS DELIVERY LAYER
    # ==========================================================
    @staticmethod
    def send_sms(phone: str, message: str) -> None:
        """
        SMS delivery via Sendchamp. 
        Uses the 'dnd' route for highest delivery success in Nigeria.
        """
        api_key = os.getenv("SENDCHAMP_API_KEY")
        if not api_key:
            print("[SMS] Skipped: SENDCHAMP_API_KEY not set")
            return

        # Sendchamp prefers numbers without the '+' sign (e.g., 23480...)
        phone = NotificationService._normalize_phone(phone).replace("+", "")

        url = "https://api.sendchamp.com/api/v1/sms/send"
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        # Sendchamp uses 'dnd', 'non_dnd', or 'international' routes.
        # 'dnd' is usually best for transactional alerts like yours.
        payload = {
            "to": [phone],
            "message": message,
            "sender_name": "SAlert", # Or your registered Sender ID (e.g., IEDLABS)
            "route": "dnd"
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            resp_data = resp.json() if resp.content else {}

            # Sendchamp success check
            if resp.status_code in [200, 201] and resp_data.get("status") == "success":
                print(f"[SENDCHAMP SUCCESS] -> {phone}")
                return
            else:
                print(f"[SENDCHAMP FAIL] {resp.status_code} - {resp.text}")

        except Exception as e:
            print(f"[SENDCHAMP ERROR] {e}")

    # ==========================================================
    # PHONE NORMALIZATION (Updated for Sendchamp)
    # ==========================================================
    @staticmethod
    def _normalize_phone(phone: str) -> str:
        if not phone:
            return phone

        phone = "".join(filter(str.isdigit, phone.strip()))

        # If it starts with 0 (e.g., 080...), change to 23480...
        if phone.startswith("0") and len(phone) == 11:
            return "234" + phone[1:]

        # If it's already 234...
        if phone.startswith("234") and len(phone) >= 13:
            return phone

        return phone