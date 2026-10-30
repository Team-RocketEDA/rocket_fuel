// Pure decision logic for the RocketEDA plugin, kept free of opencode types so it can be unit-tested.
import { realpathSync } from "node:fs"
import path from "node:path"

// Folders only the runner / project service may write. Mirrors the deny rules in harness/opencode.json;
// the plugin re-checks them on the resolved real path so symlinks and "../" can't get around them.
export const PROTECTED_DIRS = ["results", "exports", ".rocket", ".opencode", ".git"]

// Files the agent must change through tools, never by editing: the IP manifest holds verification status.
export const PROTECTED_FILES = ["ip/manifest.yaml"]

export const EDIT_TOOLS = new Set(["edit", "write", "multiedit", "patch", "apply_patch"])

// Tools that change the design or spend a repair iteration; blocked once a session hits its limit.
export const LIMITED_TOOLS = new Set([...EDIT_TOOLS, "rocket_run_job", "rocket_apply_revision"])

// Rocket tools that accept the session id the plugin attaches.
export const SESSION_TOOLS = new Set(["rocket_run_job", "rocket_ip_register"])

export type Verdict = { allow: true } | { allow: false; reason: string }

// Resolve symlinks on the longest existing prefix, so new files inside a symlinked folder are caught too.
function resolveReal(target: string): string {
  let existing = target
  const rest: string[] = []
  while (true) {
    try {
      return path.join(realpathSync(existing), ...rest.reverse())
    } catch {
      const parent = path.dirname(existing)
      if (parent === existing) return target
      rest.push(path.basename(existing))
      existing = parent
    }
  }
}

export function checkEditPath(projectDir: string, filePath: string, pdkRoots: string[] = []): Verdict {
  const root = resolveReal(path.resolve(projectDir))
  const target = resolveReal(path.resolve(root, filePath))

  for (const pdk of pdkRoots) {
    const pdkReal = resolveReal(path.resolve(pdk))
    if (target === pdkReal || target.startsWith(pdkReal + path.sep)) {
      return { allow: false, reason: `foundry PDK files are read-only: ${filePath}` }
    }
  }

  const rel = path.relative(root, target)
  if (rel === "" || rel.startsWith("..") || path.isAbsolute(rel)) {
    return { allow: false, reason: `outside the project folder: ${filePath}` }
  }
  const top = rel.split(path.sep)[0]
  if (PROTECTED_DIRS.includes(top)) {
    return { allow: false, reason: `${top}/ is written only by the runner and project service: ${filePath}` }
  }
  const relPosix = rel.split(path.sep).join("/")
  if (PROTECTED_FILES.includes(relPosix)) {
    return { allow: false, reason: `${relPosix} is changed only through the rocket tools: ${filePath}` }
  }
  return { allow: true }
}

// Collect every path an edit-type tool call would touch.
export function editTargets(args: Record<string, unknown>): string[] {
  const targets: string[] = []
  for (const key of ["filePath", "path", "file"]) {
    if (typeof args[key] === "string") targets.push(args[key] as string)
  }
  if (typeof args.patchText === "string") {
    for (const match of args.patchText.matchAll(/^\*\*\* (?:Add|Update|Delete) File: (.+)$/gm)) targets.push(match[1].trim())
    for (const match of args.patchText.matchAll(/^\*\*\* Move to: (.+)$/gm)) targets.push(match[1].trim())
  }
  return targets
}

export function hitIterationLimit(toolOutput: string): boolean {
  return toolOutput.includes("iteration_limit_reached")
}
