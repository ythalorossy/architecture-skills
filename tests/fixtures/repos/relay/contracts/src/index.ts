export const SCANNED_TOPIC = "delivery.scanned";
export const ROUTED_TOPIC = "delivery.routed";

export interface RoutedDelivery {
  route_id: number;
  reference: string;
  depot: string;
  recipient_phone: string;
}
