'use strict';

/**
 * Behavior tests for the session-end "is this session worth storing" gate.
 *
 * Run: node --test claude-hooks/tests/session-end-gate.test.js
 *
 * Regression guard for the session-summary noise bug: topics and next-steps
 * are keyword-matched on generic vocabulary ("debugging", "should", "will")
 * and fire on almost any conversation. They must NOT, on their own, make a
 * session count as meaningful - otherwise every trivial session produces a
 * generic "Session Summary" memory that scores 0.0 on quality.
 */

const { test } = require('node:test');
const assert = require('node:assert');
const { _internal } = require('../core/session-end');
const { isSessionMeaningful } = _internal;

test('topic-only session (no decisions/insights/code changes) is not meaningful', () => {
    const analysis = {
        topics: ['debugging', 'testing', 'performance'],
        decisions: [],
        insights: [],
        codeChanges: [],
        nextSteps: ['we should continue tomorrow and look at it again']
    };
    assert.strictEqual(isSessionMeaningful(analysis, { forceRemember: false }), false);
});

test('session with at least one insight is meaningful', () => {
    const analysis = {
        topics: ['debugging'],
        decisions: [],
        insights: ['learned that project detection must run before scoring'],
        codeChanges: [],
        nextSteps: []
    };
    assert.strictEqual(isSessionMeaningful(analysis, { forceRemember: false }), true);
});

test('session with a decision or a code change is meaningful', () => {
    const withDecision = { topics: [], decisions: ['chose hybrid backend'], insights: [], codeChanges: [], nextSteps: [] };
    const withCode = { topics: [], decisions: [], insights: [], codeChanges: ['implemented the gate function'], nextSteps: [] };
    assert.strictEqual(isSessionMeaningful(withDecision, { forceRemember: false }), true);
    assert.strictEqual(isSessionMeaningful(withCode, { forceRemember: false }), true);
});

test('#remember (forceRemember) bypasses the substance gate', () => {
    const empty = { topics: [], decisions: [], insights: [], codeChanges: [], nextSteps: [] };
    assert.strictEqual(isSessionMeaningful(empty, { forceRemember: true }), true);
});

test('missing or malformed analysis is not meaningful', () => {
    assert.strictEqual(isSessionMeaningful(null, { forceRemember: false }), false);
    assert.strictEqual(isSessionMeaningful(undefined, {}), false);
});
