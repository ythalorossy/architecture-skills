"""The routes database: which depot a parcel was sent to, and when."""
import os

import psycopg

DEPOTS = {"N": "north", "S": "south", "E": "east", "W": "west"}


def depot_for(reference: str) -> str:
    return DEPOTS.get(reference[:1].upper(), "north")


def record(reference: str, depot: str) -> int:
    with psycopg.connect(os.environ["ROUTES_URL"]) as connection:
        row = connection.execute(
            "INSERT INTO routes (reference, depot) VALUES (%s, %s) RETURNING id",
            (reference, depot),
        ).fetchone()
        return row[0]
