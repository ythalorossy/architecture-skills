"""The only way the router hears about a parcel, and the only way it answers."""
import json
import os

import pika

SCANNED_TOPIC = "delivery.scanned"
ROUTED_TOPIC = "delivery.routed"


def channel():
    connection = pika.BlockingConnection(pika.URLParameters(os.environ["BUS_URL"]))
    return connection.channel()


def publish(channel, topic, payload):
    channel.basic_publish(exchange="", routing_key=topic, body=json.dumps(payload).encode("utf-8"))
