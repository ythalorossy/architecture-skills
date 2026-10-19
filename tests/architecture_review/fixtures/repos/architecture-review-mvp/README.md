# Inventory Tracker (synthetic fixture)

This is a **synthetic** repository. Inventory Tracker is not a real product; it uses invented names, and its only outside hosts are reserved example domains (RFC 2606 `.example`). The code is never run.

It exists so the architecture-review skill has one small system with known problems, some of which a script can signal and some of which only a reader finds:

- **Signalled:** a database password in connection strings in `api/settings.py` and `docker-compose.yml`; a SQLAlchemy model with no migrations; both services configured with the same `DATABASE_URL`; `worker/tasks.py` importing the `api` package; no `HEALTHCHECK` and no `USER` in `worker/Dockerfile`; an endpoint with no authentication marker.
- **Found by reading:** the worker is built from `./worker`, so the `api` package it imports is not in its image; its Celery broker is `redis://localhost`, and compose defines no Redis; compose has no `depends_on`, no health checks and no database volume.

`skills/architecture-review/assets/example-review.md` is the review of this repository, and the grader scores it as a pass.
