import { afterAll, expect, test } from "bun:test"
import { FuelClient } from "../src/client"

const requests: { method: string; path: string; auth: string | null; body: string }[] = []
const server = Bun.serve({
  port: 0,
  async fetch(req) {
    const url = new URL(req.url)
    requests.push({ method: req.method, path: url.pathname, auth: req.headers.get("authorization"), body: await req.text() })
    if (url.pathname === "/event") {
      // Split one event across chunks to exercise buffering.
      const stream = new ReadableStream({
        start(controller) {
          const enc = new TextEncoder()
          controller.enqueue(enc.encode('data: {"type":"server.connected","properties":{}}\n\ndata: {"type":"session.st'))
          controller.enqueue(enc.encode('atus","properties":{"sessionID":"ses_1","status":{"type":"busy"}}}\n\n'))
          controller.close()
        },
      })
      return new Response(stream, { headers: { "Content-Type": "text/event-stream" } })
    }
    if (url.pathname === "/session") return Response.json({ id: "ses_1" })
    return Response.json(true)
  },
})
afterAll(() => server.stop())

const client = new FuelClient({ baseUrl: `http://127.0.0.1:${server.port}/`, password: "pw" })

test("creates a session, prompts and replies with basic auth", async () => {
  expect(await client.createSession("demo")).toBe("ses_1")
  await client.prompt("ses_1", "Bring this op-amp to spec.")
  await client.reply("per_9", "once")
  const [create, prompt, reply] = requests.slice(-3)
  expect(create).toMatchObject({ method: "POST", path: "/session", auth: "Basic " + btoa("opencode:pw") })
  expect(JSON.parse(prompt.body)).toEqual({ agent: "rocket-approval", parts: [{ type: "text", text: "Bring this op-amp to spec." }] })
  expect(prompt.path).toBe("/session/ses_1/prompt_async")
  expect(reply.path).toBe("/permission/per_9/reply")
  expect(JSON.parse(reply.body)).toEqual({ reply: "once" })
})

test("subscribe resolves quietly when cancelled before connecting", async () => {
  const controller = new AbortController()
  controller.abort()
  await client.subscribe(() => {}, controller.signal)
})

test("subscribe parses events split across chunks", async () => {
  const types: string[] = []
  await client.subscribe((event) => types.push(event.type))
  expect(types).toEqual(["server.connected", "session.status"])
})

test("history turns stored messages into reducer events", async () => {
  const history = new FuelClient({
    baseUrl: "http://x",
    fetch: (async (url: string) => {
      if (url.endsWith("/session")) return Response.json([{ id: "ses_old", time: { updated: 1 } }, { id: "ses_new", time: { updated: 2 } }])
      if (url.endsWith("/session/status")) return Response.json({ ses_new: { type: "retry", attempt: 3, message: "Free usage exceeded", next: 9 } })
      return Response.json([{ info: { id: "msg_1", role: "user" }, parts: [{ id: "p1", messageID: "msg_1", type: "text", text: "hi" }] }])
    }) as unknown as typeof fetch,
  })
  expect(await history.latestSession()).toBe("ses_new")
  const { emptyView, reduce } = await import("../src/view")
  const view = (await history.history("ses_new")).reduce(reduce, emptyView())
  expect(view.sessionId).toBe("ses_new")
  expect(view.messages).toEqual([{ id: "p1", role: "user", text: "hi", time: expect.any(Number) }])
  expect(view.retry).toEqual({ attempt: 3, message: "Free usage exceeded", next: 9 })
})
