import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgres://orders:dev-secret-key@db/orders"
)