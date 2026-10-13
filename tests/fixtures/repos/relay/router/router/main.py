"""Consume a scan, decide where the parcel goes, say so on the bus."""
import json

from router import bus, ledger, routes

CHARGE_CENTS = 180


def handle(channel, scan: dict) -> None:
    depot = routes.depot_for(scan["reference"])
    route_id = routes.record(scan["reference"], depot)
    ledger.append(scan["reference"], depot, CHARGE_CENTS)
    bus.publish(channel, bus.ROUTED_TOPIC, {"route_id": route_id, "depot": depot, **scan})


def main() -> None:
    channel = bus.channel()
    channel.queue_declare(queue=bus.SCANNED_TOPIC)
    for method, _, body in channel.consume(bus.SCANNED_TOPIC):
        handle(channel, json.loads(body))
        channel.basic_ack(method.delivery_tag)


if __name__ == "__main__":
    main()
