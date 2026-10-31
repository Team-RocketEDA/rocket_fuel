import { describe, expect, test } from "bun:test"
import { mkdtempSync, mkdirSync, symlinkSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { checkEditPath, editTargets, hitIterationLimit, iterationLimit } from "../src/policy"

function makeProject() {
  const root = mkdtempSync(path.join(tmpdir(), "rocket-proj-"))
  mkdirSync(path.join(root, "design"))
  mkdirSync(path.join(root, "results"))
  return root
}

describe("checkEditPath", () => {
  test("allows design files and block sources under ip/", () => {
    expect(checkEditPath(makeProject(), "design/opamp.cir").allow).toBe(true)
    expect(checkEditPath(makeProject(), "ip/opamp_2stage/opamp.cir").allow).toBe(true)
  })

  test.each(["results/opamp.dc_gain.yaml", ".rocket/stub-state.json", ".git/config", "exports/x.gds", ".opencode/opencode.json", "ip/manifest.yaml"])(
    "denies protected path %s",
    (p) => {
      expect(checkEditPath(makeProject(), p).allow).toBe(false)
    },
  )

  test("denies escaping the project", () => {
    expect(checkEditPath(makeProject(), "../elsewhere.txt").allow).toBe(false)
    expect(checkEditPath(makeProject(), "/etc/passwd").allow).toBe(false)
  })

  test("denies a symlink in design/ that points into results/", () => {
    const root = makeProject()
    symlinkSync(path.join(root, "results"), path.join(root, "design", "sneaky"))
    expect(checkEditPath(root, "design/sneaky/opamp.dc_gain.yaml").allow).toBe(false)
  })

  test("denies files under a foundry PDK root", () => {
    const root = makeProject()
    const pdk = mkdtempSync(path.join(tmpdir(), "pdk-"))
    expect(checkEditPath(root, path.join(pdk, "sky130A/models.spice"), [pdk]).allow).toBe(false)
  })
})

describe("editTargets", () => {
  test("reads filePath and patch headers", () => {
    const patchText = "*** Begin Patch\n*** Update File: design/a.cir\n*** Add File: results/fake.yaml\n*** End Patch"
    expect(editTargets({ filePath: "design/b.cir", patchText })).toEqual(["design/b.cir", "design/a.cir", "results/fake.yaml"])
  })
})

test("detects the runner's iteration-limit reply", () => {
  expect(hitIterationLimit('{"error": "iteration_limit_reached"}')).toBe(true)
  expect(hitIterationLimit('{"checks": {}}')).toBe(false)
})

test("engine run operations count as limited, engine queries don't", async () => {
  const { isLimited } = await import("../src/policy")
  expect(isLimited("engine_run_job")).toBe(true)
  expect(isLimited("engine_run_spice")).toBe(false)
  expect(isLimited("edit")).toBe(true)
  expect(isLimited("engine_get_job_status")).toBe(false)
})

test("iteration limit comes from constraints.yaml, with a fallback", () => {
  expect(iterationLimit("agent:\n  mode: approval\n  iteration_limit: 5\n")).toBe(5)
  expect(iterationLimit("agent:\n  iteration_limit: 2  # tight\n")).toBe(2)
  expect(iterationLimit("checks: []\n", 4)).toBe(4)
  expect(iterationLimit(undefined)).toBe(3)
})
