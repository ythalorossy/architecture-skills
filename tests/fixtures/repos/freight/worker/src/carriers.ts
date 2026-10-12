import { postJson } from "@freight/shared/http";

import type { ShipmentScan } from "@freight/shared/events";

/** The only place the poller talks to the carrier network. */
export class CarrierClient {
  private readonly baseUrl: string;

  constructor(baseUrl = process.env.CARRIER_API_URL ?? "") {
    this.baseUrl = baseUrl;
  }

  /** Asks the carrier network for the latest scan of each tracking number. */
  async latestScans(references: string[]): Promise<ShipmentScan[]> {
    const body = await postJson(`${this.baseUrl}/track/batch`, { tracking_numbers: references });
    return body.scans as ShipmentScan[];
  }
}
