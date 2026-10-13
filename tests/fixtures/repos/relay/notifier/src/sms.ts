import { request } from "undici";

const SMS_API_URL = process.env.SMS_API_URL ?? "https://api.sms-gate.example/v2/messages";

export async function sendText(to: string, text: string): Promise<void> {
  const response = await request(SMS_API_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ to, text }),
  });
  if (response.statusCode >= 400) {
    throw new Error(`sms provider refused the message: ${response.statusCode}`);
  }
}
