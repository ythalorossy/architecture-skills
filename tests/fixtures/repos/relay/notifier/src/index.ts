import { connect } from "amqplib";

import { ROUTED_TOPIC, RoutedDelivery } from "../../contracts/src/index";
import { sendText } from "./sms";

// The router never calls this service. The topic name is the whole contract.
async function main(): Promise<void> {
  const connection = await connect(process.env.BUS_URL!);
  const channel = await connection.createChannel();
  await channel.assertQueue(ROUTED_TOPIC);

  await channel.consume(ROUTED_TOPIC, async (message) => {
    if (!message) return;
    const delivery = JSON.parse(message.content.toString()) as RoutedDelivery;
    await sendText(delivery.recipient_phone, `Parcel ${delivery.reference} is on its way to ${delivery.depot}.`);
    channel.ack(message);
  });
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
