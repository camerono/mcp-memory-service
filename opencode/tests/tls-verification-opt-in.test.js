/**
 * Tests for the opencode plugin's TLS verification gate (#210).
 *
 * Run: node opencode/tests/tls-verification-opt-in.test.js
 *
 * #210 removed a process-wide `NODE_TLS_REJECT_UNAUTHORIZED = "0"` and an
 * unconditional insecure https.Agent, replacing them with an explicit per-request
 * opt-in. It shipped without tests because nothing under opencode/ ran in CI, so
 * a test here would have looked like coverage while never executing. The runner
 * now covers this directory, so the gate gets pinned.
 *
 * The invariant: rejectUnauthorized must stay UNSET unless the caller explicitly
 * opted in AND the request is https. Unset means Node's default, which is to
 * verify.
 */

import { test } from "node:test"
import assert from "node:assert"

import { _internal } from "../memory-plugin.js"

const { applySelfSignedCertsOption } = _internal

test("https + no opt-in leaves verification enabled", () => {
  const options = {}
  applySelfSignedCertsOption(options, true, undefined)
  assert.strictEqual(options.rejectUnauthorized, undefined)
})

test("https + explicit false leaves verification enabled", () => {
  const options = {}
  applySelfSignedCertsOption(options, true, false)
  assert.strictEqual(options.rejectUnauthorized, undefined)
})

test("https + explicit true disables verification", () => {
  const options = {}
  applySelfSignedCertsOption(options, true, true)
  assert.strictEqual(options.rejectUnauthorized, false)
})

test("plain http is a no-op even when opted in", () => {
  const options = {}
  applySelfSignedCertsOption(options, false, true)
  assert.strictEqual(options.rejectUnauthorized, undefined)
})

// Fails closed: only a real boolean true opts in. An env var that arrived as the
// string "true" must not be enough on its own — the caller is responsible for
// parsing it, and this asserts the gate does not accept truthy values.
for (const truthy of ["true", "1", 1, {}, [], "yes"]) {
  test(`truthy-but-not-true (${JSON.stringify(truthy)}) does not opt in`, () => {
    const options = {}
    applySelfSignedCertsOption(options, true, truthy)
    assert.strictEqual(options.rejectUnauthorized, undefined)
  })
}

test("opting in warns, because silently downgrading TLS is the bug", () => {
  const original = console.warn
  const warnings = []
  console.warn = (...args) => warnings.push(args.join(" "))
  try {
    applySelfSignedCertsOption({}, true, true)
  } finally {
    console.warn = original
  }
  assert.strictEqual(warnings.length, 1)
  assert.match(warnings[0], /DISABLED/)
  assert.match(warnings[0], /MITM/)
})

test("staying secure does not warn", () => {
  const original = console.warn
  const warnings = []
  console.warn = (...args) => warnings.push(args.join(" "))
  try {
    applySelfSignedCertsOption({}, true, false)
    applySelfSignedCertsOption({}, false, true)
  } finally {
    console.warn = original
  }
  assert.deepStrictEqual(warnings, [])
})

// Regression guard for what #210 actually removed: the fix must never reach for
// the process-wide switch again.
test("the gate never touches the process-wide TLS switch", () => {
  const before = process.env.NODE_TLS_REJECT_UNAUTHORIZED
  applySelfSignedCertsOption({}, true, true)
  assert.strictEqual(process.env.NODE_TLS_REJECT_UNAUTHORIZED, before)
})
