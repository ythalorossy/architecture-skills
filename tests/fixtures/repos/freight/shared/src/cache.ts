import { createClient } from "redis";

import type { ShipmentScan } from "./events.js";

const TTL_SECONDS = 120;

/** The shipment status cache, in the managed Redis instance. */
const client = createClient({ url: process.env.CACHE_URL });

export async function putStatus(reference: string, scan: ShipmentScan): Promise<void> {
  await client.setEx(`shipment:${reference}`, TTL_SECONDS, JSON.stringify(scan));
}
