import { describe, expect, test } from "bun:test"
import { mkdtempSync, mkdirSync, symlinkSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { checkEditPath, editTargets, hitIterationLimit } from "../src/policy"

function makeProject() {
  const root = mkdtempSync(path.join(tmpdir(), "rocket-proj-"))
  mkdirSync(path.join(root, "design"))
  mkdirSync(path.join(root, "results"))
  return root
}

describe("checkEditPath", () => {
  test("allows design files", () => {
    expect(checkEditPath(makeProject(), "design/opamp.cir").allow).toBe(true)
  })

  test.each(["results/opamp.dc_gain.yaml", ".rocket/stub-state.json", ".git/config", "exports/x.gds", ".opencode/opencode.json"])(
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
