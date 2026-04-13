from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.processed_webhook import ProcessedWebhook


def register_delivery_id(db: Session, delivery_id: str) -> bool:
    row = ProcessedWebhook(delivery_id=delivery_id)
    db.add(row)
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def unregister_delivery_id(db: Session, delivery_id: str) -> None:
    db.rollback()
    try:
        db.query(ProcessedWebhook).filter(ProcessedWebhook.delivery_id == delivery_id).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
