import { Client } from "pg";

import type { ShipmentScan } from "@freight/shared/events";

/** Reads and writes shipment rows in the freight PostgreSQL database. */
export class ShipmentStore {
  constructor(private readonly client: Client) {}

  static async connect(dsn = process.env.DATABASE_URL!): Promise<ShipmentStore> {
    const client = new Client({ connectionString: dsn });
    await client.connect();
    return new ShipmentStore(client);
  }

  async dueReferences(limit = 100): Promise<string[]> {
    const result = await this.client.query(
      `SELECT reference FROM shipments
       WHERE state <> 'delivered' AND checked_at < now() - interval '15 minutes'
       LIMIT $1`,
      [limit],
    );
    return result.rows.map((row) => row.reference as string);
  }

  async record(scan: ShipmentScan): Promise<void> {
    await this.client.query(
      `UPDATE shipments SET state = $1, updated_at = $2, checked_at = now() WHERE reference = $3`,
      [scan.state, scan.scannedAt, scan.reference],
    );
  }
}
