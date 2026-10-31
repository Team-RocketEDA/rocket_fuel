import { describe, expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import path from "node:path"
import { emptyView, reduce, type SessionView } from "../src/view"

const RECORDINGS = path.resolve(import.meta.dir, "../../evals/recordings")

function replay(name: string): SessionView {
  const [header, ...events] = readFileSync(path.join(RECORDINGS, `${name}.jsonl`), "utf8").trim().split("\n").map((l) => JSON.parse(l))
  let view = reduce(emptyView(), { type: "rocket.replay", properties: header })
  for (const item of events) view = reduce(view, item.event, item.t_ms)
  return view
}

describe("fix-and-register recording", () => {
  const view = replay("opamp-fix-and-register-free")

  test("is flagged as a replay and ends idle", () => {
    expect(view.replay?.model).toBe("opencode/glm-5.3-flash-free")
    expect(view.status).toBe("idle")
    expect(view.agent).toBe("rocket-approval")
  })

  test("chat starts with the user's prompt and ends with the agent's summary", () => {
    expect(view.messages[0]).toMatchObject({ role: "user", text: "Bring this op-amp to spec, then register it as a reusable block." })
    expect(view.messages.at(-1)?.role).toBe("agent")
    expect(view.messages.at(-1)?.text).toContain("UNVERIFIED")
  })

  test("the diff is on the approval card when it is asked, not only after approving", () => {
    const [header, ...events] = readFileSync(path.join(RECORDINGS, "opamp-fix-and-register-free.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l))
    let atAsk = reduce(emptyView(), { type: "rocket.replay", properties: header })
    for (const item of events) {
      atAsk = reduce(atAsk, item.event, item.t_ms)
      if (item.event.type === "permission.asked" && item.event.properties.permission === "rocket_apply_revision") break
    }
    const apply = atAsk.approvals.find((a) => a.permission === "rocket_apply_revision")!
    expect(apply.status).toBe("pending")
    expect(apply.diff).toContain("+.param L2=1.0")
    expect(apply.note).toBeUndefined()
  })

  test("with two unapplied revisions the card says so instead of guessing", () => {
    let view = emptyView("ses_a")
    for (const id of ["rev-1", "rev-2"]) {
      view = reduce(view, {
        type: "message.part.updated",
        properties: { sessionID: "ses_a", part: { id: id, callID: `c-${id}`, tool: "rocket_propose_revision", type: "tool",
          state: { status: "completed", input: {}, output: JSON.stringify({ revision_id: id, file: "design/a.cir", diff: `diff ${id}`, hypothesis: "h" }) } } },
      })
    }
    view = reduce(view, { type: "permission.asked", properties: { id: "per_1", sessionID: "ses_a", permission: "rocket_apply_revision", patterns: ["*"], metadata: {}, tool: { callID: "c-apply" } } })
    expect(view.approvals[0].diff).toBeUndefined()
    expect(view.approvals[0].note).toContain("rev-1, rev-2")
  })

  test("apply_revision approval carries the proposed diff and hypothesis", () => {
    const apply = view.approvals.find((a) => a.permission === "rocket_apply_revision")!
    expect(apply.status).toBe("approved")
    expect(apply.files).toEqual(["design/opamp.cir"])
    expect(apply.diff).toContain("+.param L2=1.0")
    expect(apply.hypothesis).toBeTruthy()
  })

  test("check table and iteration come from the runner's tool output", () => {
    expect(Object.values(view.checks).map((c) => c.status)).toEqual(["PASS", "PASS", "PASS"])
    expect(view.checks["opamp.dc_gain"].producer).toBe("stub")
    expect(view.iteration).toEqual({ used: 1, limit: 3, left: 2, limitReached: false })
    expect(view.lastChanges.some((line) => line.includes("+.param L2=1.0"))).toBe(true)
  })

  test("tool steps are labelled and finished", () => {
    expect(view.steps.find((s) => s.tool === "rocket_run_job")?.label).toBe("Run simulation")
    expect(view.steps.every((s) => s.status === "completed")).toBe(true)
  })
})

describe("edit-approval recording", () => {
  const view = replay("opamp-approval-free")

  test("four edit approvals, each with the file and its diff", () => {
    expect(view.approvals).toHaveLength(4)
    for (const approval of view.approvals) {
      expect(approval.permission).toBe("edit")
      expect(approval.files).toEqual(["/project/design/opamp.cir"])
      expect(approval.diff).toContain("@@")
      expect(approval.status).toBe("approved")
    }
  })

  test("the check table follows the last run, not the chat", () => {
    expect(view.checks["opamp.phase_margin"]).toMatchObject({ status: "PASS", measured: 60 })
    expect(view.iteration).toMatchObject({ used: 3, left: 0 })
  })
})

describe("reduce", () => {
  test("ignores events from other sessions once bound", () => {
    const view = reduce(emptyView("ses_a"), {
      type: "permission.asked",
      properties: { id: "per_1", sessionID: "ses_b", permission: "edit", patterns: ["design/x"], metadata: {} },
    })
    expect(view.approvals).toHaveLength(0)
  })

  test("streams text deltas into the message", () => {
    let view = emptyView("ses_a")
    view = reduce(view, { type: "message.updated", properties: { sessionID: "ses_a", info: { id: "msg_1", role: "assistant" } } })
    view = reduce(view, { type: "message.part.updated", properties: { sessionID: "ses_a", part: { id: "prt_1", messageID: "msg_1", type: "text", text: "" } } })
    view = reduce(view, { type: "message.part.delta", properties: { sessionID: "ses_a", partID: "prt_1", field: "text", delta: "gain " } })
    view = reduce(view, { type: "message.part.delta", properties: { sessionID: "ses_a", partID: "prt_1", field: "text", delta: "52 dB" } })
    expect(view.messages).toEqual([{ id: "prt_1", role: "agent", text: "gain 52 dB", time: expect.any(Number) }])
  })

  test("reasoning deltas never reach the chat", () => {
    let view = emptyView("ses_a")
    view = reduce(view, { type: "message.part.updated", properties: { sessionID: "ses_a", part: { id: "prt_r", messageID: "m", type: "reasoning", text: "" } } })
    view = reduce(view, { type: "message.part.delta", properties: { sessionID: "ses_a", partID: "prt_r", field: "text", delta: "thinking" } })
    expect(view.messages).toHaveLength(0)
  })

  test("a rejected approval is marked rejected", () => {
    let view = reduce(emptyView("ses_a"), {
      type: "permission.asked",
      properties: { id: "per_1", sessionID: "ses_a", permission: "edit", patterns: ["design/x"], metadata: { filepath: "/p/design/x", diff: "@@" } },
    })
    view = reduce(view, { type: "permission.replied", properties: { sessionID: "ses_a", requestID: "per_1", reply: "reject" } })
    expect(view.approvals[0].status).toBe("rejected")
  })

  test("iteration limit from the runner sets limitReached", () => {
    const view = reduce(emptyView("ses_a"), {
      type: "message.part.updated",
      properties: {
        sessionID: "ses_a",
        part: { id: "p", callID: "c", tool: "rocket_run_job", type: "tool", state: { status: "completed", input: {}, output: JSON.stringify({ error: "iteration_limit_reached", iteration_limit: 3 }) } },
      },
    })
    expect(view.iteration).toMatchObject({ limit: 3, left: 0, limitReached: true })
  })

  test("session errors surface the message", () => {
    const view = reduce(emptyView("ses_a"), { type: "session.error", properties: { sessionID: "ses_a", error: { name: "APIError", data: { message: "Unauthorized" } } } })
    expect(view).toMatchObject({ status: "error", error: "Unauthorized" })
  })
})

test("each executed engine run counts as one repair attempt", () => {
  const run = (callID: string, output: unknown) => ({
    type: "message.part.updated",
    properties: { part: { id: callID, callID, tool: "engine_run_job", type: "tool", state: { status: "completed", input: { request_id: "r" }, output: JSON.stringify(output) } } },
  })
  let view = emptyView()
  view = reduce(view, run("c1", { run_id: "a", state: "completed", verdict: { status: "FAIL" } }))
  view = reduce(view, run("c2", { run_id: "b", state: "completed", verdict: { status: "PASS" } }))
  view = reduce(view, run("c2", { run_id: "b", state: "completed", verdict: { status: "PASS" } }))
  view = reduce(view, run("c3", { ok: false, code: "unknown_request" }))
  expect(view.iteration?.used).toBe(2)
  expect(view.steps.map((s) => s.label)).toEqual(["Run simulation", "Run simulation", "Run simulation"])
})
