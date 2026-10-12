# Freight (synthetic fixture)

This is a **synthetic** repository. Freight is not a real product; it uses invented names, and its only
outside hosts are reserved example domains (RFC 2606 `.example`). The code is never run.

## What it is

Freight tracks parcels that other companies carry. A dispatcher asks it where a shipment is; a
background poller keeps the answers fresh by asking the carrier network for new scans.

- **Dispatchers** query shipment status over the HTTP API (`GET /api/shipments/{reference}`) and pull
  the list of late shipments at the start of a shift. There is no UI yet.
- `api/` — the **tracking API**. Answers from the shipment status cache, falling back to the
  shipments database.
- `worker/` — the **poller**. Runs on a timer, asks the carrier network for the latest scans of the
  shipments that are due a check, writes what it learns to the shipments database and refreshes the
  cached status so the API does not serve a stale state.
- `shared/` — helpers both services use. A library; it is not deployed and does not run on its own.

## Running it locally

`docker compose up` starts the database, the API and the poller. The compose file also starts an
Adminer console on `:8081` so the team can look at the database by hand; it is a local convenience
and is not part of any deployment. `npm run mock` in `worker/` starts a json-server stub of the
carrier network, so the poller can be exercised without calling anyone.

The status cache is a managed Redis instance in every environment, including locally, so it is not a
compose service — the services reach it through `CACHE_URL`.
