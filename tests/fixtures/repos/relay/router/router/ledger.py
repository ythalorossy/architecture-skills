"""
Appends routed parcels to the finance platform's ledger.

The ledger belongs to the finance platform: they run it, they bill the depots
from it, and they own the schema. Relay only ever appends to it. Everything
that touches it goes through this module so there is one place to change when
finance asks us to.
"""
import os

import psycopg


def append(reference: str, depot: str, charge_cents: int) -> None:
    with psycopg.connect(os.environ["LEDGER_URL"]) as connection:
        connection.execute(
            "INSERT INTO ledger_entries (reference, depot, charge_cents) VALUES (%s, %s, %s)",
            (reference, depot, charge_cents),
        )
