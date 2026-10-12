"""The only place the API talks to the status cache."""
import json
import os

import redis

TTL_SECONDS = 120


class StatusCache:
    """Shipment status, cached for two minutes in the managed Redis instance."""

    def __init__(self, url: str = None):
        self.client = redis.Redis.from_url(url or os.environ["CACHE_URL"])

    def get(self, reference: str):
        raw = self.client.get(f"shipment:{reference}")
        return json.loads(raw) if raw else None

    def put(self, reference: str, shipment: dict) -> None:
        self.client.setex(f"shipment:{reference}", TTL_SECONDS, json.dumps(shipment, default=str))
