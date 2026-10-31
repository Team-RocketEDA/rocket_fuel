// Minimal opencode server client for the RocketEDA UI. No dependencies; uses fetch.
// In Electron, run it in main (it holds the password) or point the renderer at a proxy that adds auth.

import type { OpencodeEvent } from "./view"

export type Reply = "once" | "always" | "reject"

export type ClientOptions = {
  baseUrl: string
  password?: string
  username?: string
  fetch?: typeof fetch
}

export class FuelClient {
  private readonly baseUrl: string
  private readonly auth?: string
  private readonly fetchImpl: typeof fetch

  constructor(options: ClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "")
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis)
    if (options.password) this.auth = "Basic " + btoa(`${options.username ?? "opencode"}:${options.password}`)
  }

  private async request(method: string, path: string, body?: unknown): Promise<any> {
    const headers: Record<string, string> = { "Content-Type": "application/json" }
    if (this.auth) headers.Authorization = this.auth
    const response = await this.fetchImpl(this.baseUrl + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
    if (!response.ok) throw new Error(`${method} ${path} failed: ${response.status} ${await response.text()}`)
    const text = await response.text()
    return text ? JSON.parse(text) : undefined
  }

  async createSession(title = "RocketEDA session"): Promise<string> {
    const session = await this.request("POST", "/session", { title })
    return session.id
  }

  // Returns once the prompt is accepted; the agent's work arrives on the event stream.
  async prompt(sessionId: string, text: string, agent = "rocket-approval"): Promise<void> {
    await this.request("POST", `/session/${sessionId}/prompt_async`, { agent, parts: [{ type: "text", text }] })
  }

  async reply(permissionId: string, reply: Reply, message?: string): Promise<void> {
    await this.request("POST", `/permission/${permissionId}/reply`, message ? { reply, message } : { reply })
  }

  // Most recently updated session, so a reloaded UI can pick the conversation back up.
  async latestSession(): Promise<string | undefined> {
    const sessions: { id: string; time: { updated: number } }[] = await this.request("GET", "/session")
    return sessions.sort((a, b) => b.time.updated - a.time.updated)[0]?.id
  }

  // A session's stored messages as the events that produced them, for reduce().
  async history(sessionId: string): Promise<OpencodeEvent[]> {
    const messages: { info: Record<string, any>; parts: Record<string, any>[] }[] = await this.request("GET", `/session/${sessionId}/message`)
    const events: OpencodeEvent[] = [{ type: "session.created", properties: { sessionID: sessionId, info: { id: sessionId } } }]
    for (const message of messages) {
      events.push({ type: "message.updated", properties: { sessionID: sessionId, info: message.info } })
      for (const part of message.parts) events.push({ type: "message.part.updated", properties: { sessionID: sessionId, part } })
    }
    // Where the session is now (busy, or retrying a failed model call); idle sessions aren't listed.
    const statuses: Record<string, unknown> = await this.request("GET", "/session/status")
    const status = statuses?.[sessionId]
    if (status) events.push({ type: "session.status", properties: { sessionID: sessionId, status } })
    return events
  }

  async abort(sessionId: string): Promise<void> {
    await this.request("POST", `/session/${sessionId}/abort`)
  }

  // Streams server-sent events until the signal aborts or the server closes the stream.
  async subscribe(onEvent: (event: OpencodeEvent) => void, signal?: AbortSignal): Promise<void> {
    const headers: Record<string, string> = { Accept: "text/event-stream" }
    if (this.auth) headers.Authorization = this.auth
    let response: Response
    try {
      response = await this.fetchImpl(this.baseUrl + "/event", { headers, signal })
    } catch (error) {
      if (signal?.aborted) return
      throw error
    }
    if (!response.ok || !response.body) throw new Error(`GET /event failed: ${response.status}`)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) return
        buffer += decoder.decode(value, { stream: true })
        let boundary: number
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const chunk = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          const data = chunk
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart())
            .join("\n")
          if (data) onEvent(JSON.parse(data))
        }
      }
    } catch (error) {
      if (signal?.aborted) return
      throw error
    }
  }
}
