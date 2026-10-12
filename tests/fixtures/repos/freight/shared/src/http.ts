/** Thin JSON-over-HTTP helper. The services post through this, never directly. */
const TIMEOUT_MS = 10_000;

export async function postJson(url: string, payload: unknown): Promise<Record<string, unknown>> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!response.ok) {
    throw new Error(`${url} answered ${response.status}`);
  }
  return (await response.json()) as Record<string, unknown>;
}
