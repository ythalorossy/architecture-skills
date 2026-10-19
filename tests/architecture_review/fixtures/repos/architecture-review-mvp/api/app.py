from fastapi import FastAPI
from .models import get_items

app = FastAPI()


@app.get("/items")
def list_items():
    items = get_items()
    return {"items": items}