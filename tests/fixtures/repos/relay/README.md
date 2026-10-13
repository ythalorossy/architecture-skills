# Relay (synthetic fixture)

This is a **synthetic** repository. Relay is not a real product; it uses invented names, and its only
outside hosts are reserved example domains (RFC 2606 `.example`). The code is never run.

## What it is

Relay moves delivery scans from the handheld devices couriers carry to the people and systems that
need to know. Nothing in it calls anything else directly: every service talks to the message bus.

- A **courier** scans a parcel on a handheld. The handheld posts the scan to the intake API
  (`POST /scans`); there is no UI and no other client.
- `intake/` — the **intake API** (Go). Validates a scan and publishes it to the bus as
  `delivery.scanned`. It writes to no database: the bus is its only output.
- `router/` — the **router** (Python). Consumes `delivery.scanned`, decides which depot the parcel
  belongs to, records the route in the routes database, and publishes `delivery.routed`.
- `notifier/` — the **notifier** (Node). Consumes `delivery.routed` and texts the recipient through
  the SMS provider. It never talks to the router, and the router does not know it exists: the topic
  name is the whole of the contract between them.
- `contracts/` — the topic names and payload types the three services agree on. A library; it is not
  deployed and does not run on its own.

## The ledger is not ours

The router also appends every routed parcel to the **ledger**, a database the finance platform owns
and runs. Finance reads it to bill the depots; we only ever write to it, through
`router/ledger.py`, and the connection string points at their host (`ledger.finance.example`). It is
not in our compose file and nobody here may change its schema: ask the finance team.

## Running it locally

`docker compose up` starts the bus, the routes database and the three services. It also starts a
Mailpit inbox on `:8025` so the team can read the messages the notifier would have sent instead of
paying for them; that is a local convenience and is never deployed. `npm run mock` in `notifier/`
starts a json-server stub of the SMS provider for the same reason.
