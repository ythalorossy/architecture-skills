import { putStatus } from "@freight/shared/cache";

import { CarrierClient } from "./carriers.js";
import { ShipmentStore } from "./shipments.js";

const INTERVAL_SECONDS = Number(process.env.POLL_SECONDS ?? "60");

/** Keeps shipment states fresh: ask the carrier network, write what changed. */
export async function pollOnce(carriers: CarrierClient, store: ShipmentStore): Promise<number> {
  const references = await store.dueReferences();
  if (references.length === 0) {
    return 0;
  }
  for (const scan of await carriers.latestScans(references)) {
    await store.record(scan);
    // The API serves status from the cache, so a stale entry would hide this scan.
    await putStatus(scan.reference, scan);
  }
  return references.length;
}

export async function main(): Promise<void> {
  const carriers = new CarrierClient();
  const store = await ShipmentStore.connect();
  for (;;) {
    await pollOnce(carriers, store);
    await new Promise((resolve) => setTimeout(resolve, INTERVAL_SECONDS * 1000));
  }
}

await main();
