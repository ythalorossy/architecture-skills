import os

import psycopg

from freight.storage.cache import StatusCache

COLUMNS = ("reference", "carrier", "state", "updated_at")


class ShipmentRepository:
    """Reads shipments from the freight PostgreSQL database."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    def find(self, reference: str):
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT reference, carrier, state, updated_at FROM shipments WHERE reference = %s",
                (reference,),
            ).fetchone()
        return dict(zip(COLUMNS, row)) if row else None

    def late(self, limit: int):
        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute(
                "SELECT reference, carrier, state, updated_at FROM shipments "
                "WHERE state <> 'delivered' AND due_at < now() LIMIT %s",
                (limit,),
            ).fetchall()
        return [dict(zip(COLUMNS, row)) for row in rows]


class TrackingService:
    """Answers shipment status questions, cache first."""

    def __init__(self, repository: ShipmentRepository = None, cache: StatusCache = None):
        self.repository = repository or ShipmentRepository(os.environ["DATABASE_URL"])
        self.cache = cache or StatusCache()

    def status(self, reference: str):
        cached = self.cache.get(reference)
        if cached is not None:
            return cached
        shipment = self.repository.find(reference)
        if shipment is not None:
            self.cache.put(reference, shipment)
        return shipment

    def late(self, limit: int):
        return self.repository.late(limit)
