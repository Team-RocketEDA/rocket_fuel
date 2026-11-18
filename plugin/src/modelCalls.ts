// Provider-neutral model-call telemetry from opencode's event bus.
//
// opencode reports an assistant message after each model turn with its provider,
// model and token usage. We turn only those facts into a log record: no prompt,
// no message text, no headers and no key. This works for every provider because
// it is opencode's own accounting, not a protocol-specific proxy.

export type ModelCallRecord = {
  at: string
  event: "call"
  provider: string
  model: string
  status: number
  duration_ms: number
  input_tokens: number | null
  output_tokens: number | null
  timestamp: string
  session_id: string
  message_id: string
  agent?: string
}

function statusOf(message: any): number {
  const status = message?.error?.data?.statusCode ?? message?.error?.statusCode
  return typeof status === "number" ? status : message?.error ? 500 : 200
}

// Returns a record only for a completed assistant message. `message.updated`
// fires repeatedly while a turn streams, so `time.completed` is the gate.
export function modelCallRecord(event: any): ModelCallRecord | null {
  if (event?.type !== "message.updated") return null
  const message = event?.properties?.info
  if (!message || message.role !== "assistant" || !message.time?.completed) return null
  const completed = Number(message.time.completed)
  const created = Number(message.time.created)
  if (!Number.isFinite(completed)) return null
  const tokens = message.tokens ?? {}
  return {
    at: new Date(completed).toISOString(),
    event: "call",
    provider: String(message.providerID ?? "unknown"),
    model: String(message.modelID ?? "unknown"),
    status: statusOf(message),
    duration_ms: Number.isFinite(created) ? Math.max(0, completed - created) : 0,
    input_tokens: Number.isFinite(tokens.input) ? tokens.input : null,
    output_tokens: Number.isFinite(tokens.output) ? tokens.output : null,
    timestamp: new Date(completed).toISOString(),
    session_id: String(message.sessionID ?? ""),
    message_id: String(message.id ?? ""),
    ...(message.mode ? { agent: String(message.mode) } : {}),
  }
}
