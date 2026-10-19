from celery import Celery
from api.app import app
from api.models import Item

celery_app = Celery("tasks", broker="redis://localhost")


@celery_app.task
def process_item(item_id: int):
    return {"item_id": item_id}