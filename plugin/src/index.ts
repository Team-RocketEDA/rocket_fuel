// RocketEDA opencode plugin: protected paths, repair-iteration lock, session ids and audit log.
// See harness/README.md sections 5.3, 8.3 and 13 in the PRD repo.
import type { Plugin } from "@opencode-ai/plugin"
import { appendFileSync, mkdirSync } from "node:fs"
import path from "node:path"
import { checkEditPath, EDIT_TOOLS, editTargets, hitIterationLimit, isLimited, SESSION_TOOLS } from "./policy"

export const RocketPlugin: Plugin = async ({ directory }) => {
  const pdkRoots = (process.env.ROCKET_PDK_ROOTS ?? "").split(path.delimiter).filter(Boolean)
  const lockedSessions = new Set<string>()
  const auditDir = path.join(directory, ".rocket")

  function audit(entry: Record<string, unknown>) {
    try {
      mkdirSync(auditDir, { recursive: true })
      appendFileSync(path.join(auditDir, "audit.jsonl"), JSON.stringify({ ts: new Date().toISOString(), ...entry }) + "\n")
    } catch {
      // Auditing must never take down the agent; the runner keeps its own job records.
    }
  }

  audit({ event: "plugin_loaded", pdkRoots })

  return {
    "tool.execute.before": async (input, output) => {
      const { tool, sessionID } = input

      if (lockedSessions.has(sessionID) && isLimited(tool)) {
        audit({ sessionID, tool, blocked: "iteration_limit" })
        throw new Error("Repair iteration limit reached for this session. Stop and summarise the failures for the user.")
      }

      if (EDIT_TOOLS.has(tool)) {
        for (const target of editTargets(output.args ?? {})) {
          const verdict = checkEditPath(directory, target, pdkRoots)
          if (!verdict.allow) {
            audit({ sessionID, tool, target, blocked: verdict.reason })
            throw new Error(`Blocked by RocketEDA: ${verdict.reason}`)
          }
        }
      }

      if (SESSION_TOOLS.has(tool)) {
        output.args = { ...output.args, rocket_session: sessionID }
      }

      if (tool.startsWith("rocket_") || tool.startsWith("engine_") || EDIT_TOOLS.has(tool)) {
        audit({ sessionID, tool, callID: input.callID })
      }
    },

    "tool.execute.after": async (input, output) => {
      // MCP results don't arrive in output.output alone, so search the whole result.
      if (input.tool === "rocket_run_job" && hitIterationLimit(JSON.stringify(output))) {
        lockedSessions.add(input.sessionID)
        audit({ sessionID: input.sessionID, event: "iteration_limit_reached" })
      }
    },
  }
}
