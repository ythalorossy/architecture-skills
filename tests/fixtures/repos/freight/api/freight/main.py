from fastapi import FastAPI

from freight.tracking.service import TrackingService

app = FastAPI(title="Freight Tracking API")
tracking = TrackingService()


@app.get("/api/shipments/{reference}")
def get_shipment(reference: str):
    return tracking.status(reference)


@app.get("/api/shipments")
def list_late_shipments(limit: int = 50):
    return tracking.late(limit)
