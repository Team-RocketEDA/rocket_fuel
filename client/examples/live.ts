// Drive a live session through FuelClient and print the chat-panel view as it changes.
// Start a server first:   OPENCODE_SERVER_PASSWORD=dev scripts/dev.sh "$(scripts/new-demo.sh)" serve --port 4097
// Then:                   OPENCODE_SERVER_PASSWORD=dev bun client/examples/live.ts [--approve] [prompt]
// Without --approve, approval requests are rejected, which shows the agent being refused.
import { emptyView, FuelClient, reduce, type SessionView } from "../src"

const approve = process.argv.includes("--approve")
const prompt = process.argv.slice(2).filter((a) => a !== "--approve").join(" ") || "Bring this op-amp to spec."
const client = new FuelClient({ baseUrl: process.env.ROCKET_AGENT_URL ?? "http://127.0.0.1:4097", password: process.env.OPENCODE_SERVER_PASSWORD })

const sessionId = await client.createSession("live example")
let view: SessionView = emptyView(sessionId)
const seen = new Set<string>()
const stop = new AbortController()
let started = false

const done = client.subscribe(async (event) => {
  view = reduce(view, event)
  for (const step of view.steps) {
    const key = `step:${step.id}:${step.status}`
    if ((step.status === "completed" || step.status === "error") && !seen.has(key)) {
      seen.add(key)
      console.log(`  [${step.status}] ${step.label}`)
    }
  }
  for (const approval of view.approvals) {
    if (approval.status === "pending" && !seen.has(approval.id)) {
      seen.add(approval.id)
      console.log(`  APPROVAL ${approval.label} ${approval.files.join(", ")}\n${(approval.diff ?? "(no diff)").split("\n").map((l) => "    | " + l).join("\n")}`)
      await client.reply(approval.id, approve ? "once" : "reject")
    }
  }
  if (event.type === "session.status" && view.status === "busy") started = true
  if (started && (view.status === "idle" || view.status === "error")) stop.abort()
}, stop.signal)

await client.prompt(sessionId, prompt)
await done

console.log("\nchecks:", Object.fromEntries(Object.entries(view.checks).map(([id, c]) => [id, `${c.status} ${c.measured ?? ""}`])))
console.log("iteration:", view.iteration, "status:", view.status, view.error ?? "")
console.log("\nfinal message:\n" + (view.messages.at(-1)?.text ?? "(none)"))
