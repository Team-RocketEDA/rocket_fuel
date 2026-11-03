// Turns opencode's event stream into what a chat panel shows. Pure: (view, event) -> view.
// Works the same for live events and recorded ones served by evals/replay_server.py.

export type CheckStatus = "PASS" | "FAIL" | "NOT_RUN" | "UNSUPPORTED"
export type StepStatus = "pending" | "running" | "completed" | "error"

export type ChatMessage = { id: string; role: "user" | "agent"; text: string; time: number }

export type ToolStep = {
  id: string
  tool: string
  label: string
  status: StepStatus
  input: Record<string, unknown>
  output?: string
  error?: string
  time: number
}

export type Approval = {
  id: string
  callId?: string
  permission: string
  label: string
  files: string[]
  diff?: string
  hypothesis?: string
  // Set when the diff can't be pinned to one revision; the UI should say so rather than guess.
  note?: string
  status: "pending" | "approved" | "rejected"
  time: number
}

export type CheckResult = {
  status: CheckStatus
  measured?: number
  target?: string
  margin?: number
  required?: boolean
  design?: string
  producer?: string
}

export type SessionView = {
  sessionId?: string
  status: "idle" | "busy" | "error"
  error?: string
  // Set while opencode retries a failed model call (rate limit, used-up free quota, provider down).
  retry?: { attempt: number; message: string; next?: number }
  agent?: string
  model?: string
  replay?: { recordedAt?: string; model?: string; note?: string }
  messages: ChatMessage[]
  steps: ToolStep[]
  approvals: Approval[]
  checks: Record<string, CheckResult>
  iteration?: { used: number; limit?: number; left?: number; limitReached: boolean }
  lastChanges: string[]
  // internal lookups, kept on the view so the reducer stays pure
  countedRuns: string[]
  roles: Record<string, "user" | "assistant">
  partKinds: Record<string, string>
  revisions: Record<string, { file: string; diff: string; hypothesis: string; applied: boolean }>
}

export type OpencodeEvent = { type: string; properties?: Record<string, any> }

export function emptyView(sessionId?: string): SessionView {
  return {
    sessionId,
    status: "idle",
    messages: [],
    steps: [],
    approvals: [],
    checks: {},
    lastChanges: [],
    countedRuns: [],
    roles: {},
    partKinds: {},
    revisions: {},
  }
}

const LABELS: Record<string, string> = {
  read: "Read file",
  edit: "Edit file",
  write: "Write file",
  glob: "Find files",
  grep: "Search files",
  list: "List folder",
  todowrite: "Update plan",
  rocket_get_constraints: "Read constraints",
  rocket_get_status: "Check status",
  rocket_list_job_kinds: "List job kinds",
  rocket_run_job: "Run simulation",
  rocket_get_job_status: "Job status",
  rocket_get_check_results: "Read check results",
  rocket_get_logs: "Search logs",
  rocket_propose_revision: "Propose change",
  rocket_apply_revision: "Apply change",
  rocket_propose_constraint_change: "Propose constraint change",
  rocket_ip_search: "Search IP library",
  rocket_ip_get: "Read IP block",
  rocket_ip_register: "Register IP block",
  engine_run_spice: "Run simulation",
  engine_run_job: "Record result",
  engine_get_job_status: "Read result",
  engine_get_check_results: "Read check results",
  engine_get_logs: "Search logs",
  engine_list_job_kinds: "List job kinds",
  engine_get_project_snapshot: "Read project state",
}

export function toolLabel(tool: string): string {
  if (LABELS[tool]) return LABELS[tool]
  const words = tool.replace(/^rocket_/, "").split("_").join(" ")
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function parseJson(text: unknown): any {
  if (typeof text !== "string") return undefined
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}

function upsert<T extends { id: string }>(list: T[], item: T): T[] {
  const index = list.findIndex((x) => x.id === item.id)
  if (index === -1) return [...list, item]
  const next = list.slice()
  next[index] = item
  return next
}

// Check results, iteration and revisions come only from rocket tool outputs, never from chat text.
function applyToolResult(view: SessionView, tool: string, input: Record<string, any>, output: any): SessionView {
  if (!output || typeof output !== "object") return view
  let next = view
  if ((tool === "rocket_run_job" || tool === "rocket_get_check_results") && output.checks) {
    next = { ...next, checks: output.checks }
  }
  if (tool === "rocket_run_job") {
    if (output.error === "iteration_limit_reached") {
      next = { ...next, iteration: { used: next.iteration?.used ?? 0, limit: output.iteration_limit, left: 0, limitReached: true } }
    } else if (typeof output.iteration === "number") {
      const limit = next.iteration?.limit
      next = { ...next, iteration: { used: output.iteration, limit, left: output.iterations_left, limitReached: false } }
    }
    if (Array.isArray(output.changes_since_last_run)) next = { ...next, lastChanges: output.changes_since_last_run }
  }
  if (tool === "rocket_get_status" && typeof output.iteration === "number") {
    next = {
      ...next,
      iteration: { used: output.iteration, limit: output.iteration_limit, left: output.iterations_left, limitReached: !!output.limit_reached },
    }
  }
  // Each executed engine run is one repair attempt, whichever call reports it; the plugin locks the session at the limit.
  const runIds = [output.request_id, output.run_id].filter((id) => typeof id === "string")
  if (
    tool.startsWith("engine_run_") &&
    output.verdict &&
    !["NOT_RUN", "UNSUPPORTED"].includes(output.verdict.status) &&
    !runIds.some((id) => next.countedRuns.includes(id))
  ) {
    next = { ...next, countedRuns: [...next.countedRuns, ...runIds] }
    const used = (next.iteration?.used ?? 0) + 1
    const limit = next.iteration?.limit
    next = { ...next, iteration: { used, limit, left: limit === undefined ? undefined : Math.max(0, limit - used), limitReached: limit !== undefined && used >= limit } }
  }
  if (tool === "rocket_propose_revision" && output.revision_id) {
    next = {
      ...next,
      revisions: {
        ...next.revisions,
        [output.revision_id]: { file: output.file, diff: output.diff, hypothesis: output.hypothesis ?? input.hypothesis, applied: false },
      },
    }
  }
  if (tool === "rocket_apply_revision" && output.revision_id && !output.error && next.revisions[output.revision_id]) {
    next = { ...next, revisions: { ...next.revisions, [output.revision_id]: { ...next.revisions[output.revision_id], applied: true } } }
  }
  return next
}

function applyPart(view: SessionView, part: any, time: number): SessionView {
  const kinds = { ...view.partKinds, [part.id]: part.type }
  let next = { ...view, partKinds: kinds }

  if (part.type === "text" && !part.synthetic) {
    const role = view.roles[part.messageID] === "user" ? "user" : "agent"
    const existing = view.messages.find((m) => m.id === part.id)
    return { ...next, messages: upsert(next.messages, { id: part.id, role, text: part.text ?? "", time: existing?.time ?? time }) }
  }

  if (part.type === "tool") {
    const state = part.state ?? {}
    const existing = view.steps.find((s) => s.id === part.callID)
    const step: ToolStep = {
      id: part.callID,
      tool: part.tool,
      label: toolLabel(part.tool),
      status: state.status,
      input: state.input ?? existing?.input ?? {},
      output: typeof state.output === "string" ? state.output : existing?.output,
      error: state.error,
      time: existing?.time ?? state.time?.start ?? time,
    }
    next = { ...next, steps: upsert(next.steps, step) }
    // Apply a result once: the same completed part can arrive again (restored history, then the live stream).
    if (state.status === "completed" && existing?.status !== "completed") {
      next = applyToolResult(next, part.tool, step.input, parseJson(state.output))
    }
    // The approval for apply_revision can arrive before the call's arguments do.
    const waiting = next.approvals.find((a) => a.callId === part.callID && !a.diff)
    const rev = next.revisions[step.input.revision_id as string]
    if (waiting && rev) {
      next = { ...next, approvals: upsert(next.approvals, { ...waiting, diff: rev.diff, hypothesis: rev.hypothesis, files: [rev.file], note: undefined }) }
    }
    return next
  }
  return next
}

function applyPermission(view: SessionView, props: any, time: number): SessionView {
  const metadata = props.metadata ?? {}
  const files: string[] = metadata.filepath ? [metadata.filepath] : (props.patterns ?? []).filter((p: string) => p !== "*")
  let diff: string | undefined = metadata.diff
  let hypothesis: string | undefined

  // opencode asks before the call's arguments are known, so apply_revision has no revision id yet.
  // Exactly one proposed-but-unapplied revision means that is the one; otherwise don't guess.
  let note: string | undefined
  if (!diff && props.permission === "rocket_apply_revision") {
    const step = view.steps.find((s) => s.id === props.tool?.callID)
    const known = step?.input?.revision_id as string | undefined
    const candidates = known ? [known] : Object.keys(view.revisions).filter((id) => !view.revisions[id].applied)
    if (candidates.length === 1 && view.revisions[candidates[0]]) {
      const rev = view.revisions[candidates[0]]
      diff = rev.diff
      hypothesis = rev.hypothesis
      files.push(rev.file)
    } else {
      note = candidates.length ? `One of ${candidates.length} proposed revisions (${candidates.join(", ")}); the exact one is known only after approval.` : "No proposed revision found for this change."
    }
  }

  const approval: Approval = {
    id: props.id,
    callId: props.tool?.callID,
    permission: props.permission,
    label: toolLabel(props.permission),
    files,
    diff,
    hypothesis,
    note,
    status: "pending",
    time,
  }
  return { ...view, approvals: upsert(view.approvals, approval) }
}

export function reduce(view: SessionView, event: OpencodeEvent, time = Date.now()): SessionView {
  const props = event.properties ?? {}
  if (event.type === "rocket.replay") {
    return { ...view, replay: { recordedAt: props.recorded_at, model: props.model, note: props.note } }
  }

  // Once bound to a session, ignore other sessions' events (one opencode server can host several).
  const sessionId = props.sessionID ?? props.info?.sessionID ?? props.part?.sessionID
  if (view.sessionId && sessionId && sessionId !== view.sessionId) return view

  switch (event.type) {
    case "session.created":
      return view.sessionId ? view : { ...view, sessionId: props.info?.id ?? sessionId }
    case "session.updated":
      return {
        ...view,
        agent: props.info?.agent ?? view.agent,
        model: props.info?.model ? `${props.info.model.providerID}/${props.info.model.id}` : view.model,
      }
    case "session.status": {
      const status = props.status ?? {}
      // A retry keeps the session busy, but the user should see why nothing is happening.
      if (status.type === "retry") {
        return { ...view, status: "busy", retry: { attempt: status.attempt ?? 1, message: status.message ?? "Model call failed", next: status.next } }
      }
      return status.type === "busy" || status.type === "idle" ? { ...view, status: status.type, retry: undefined } : view
    }
    case "session.idle":
      return { ...view, status: view.status === "error" ? "error" : "idle", retry: undefined }
    case "session.error":
      return { ...view, status: "error", error: props.error?.data?.message ?? props.error?.name ?? "Agent error" }
    case "message.updated": {
      if (!props.info?.id) return view
      // Assistant messages carry the model that wrote them, which also covers restored history.
      const model = props.info.providerID && props.info.modelID ? `${props.info.providerID}/${props.info.modelID}` : view.model
      return { ...view, model, agent: props.info.agent ?? view.agent, roles: { ...view.roles, [props.info.id]: props.info.role } }
    }
    case "message.part.updated":
      // Prefer the part's own timestamp, so restored history keeps messages and tool calls in order.
      return props.part ? applyPart(view, props.part, props.part.time?.start ?? props.time ?? time) : view
    case "message.part.delta": {
      if (view.partKinds[props.partID] !== "text" || props.field !== "text") return view
      const message = view.messages.find((m) => m.id === props.partID)
      return message ? { ...view, messages: upsert(view.messages, { ...message, text: message.text + props.delta }) } : view
    }
    case "permission.asked":
      return applyPermission(view, props, time)
    case "permission.replied": {
      const approval = view.approvals.find((a) => a.id === props.requestID)
      if (!approval) return view
      return { ...view, approvals: upsert(view.approvals, { ...approval, status: props.reply === "reject" ? "rejected" : "approved" }) }
    }
    default:
      return view
  }
}
