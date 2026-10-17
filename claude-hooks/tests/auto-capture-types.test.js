'use strict';

/**
 * Regression guard for #177: the memory types the hooks send must exist in the
 * server ontology.
 *
 * Every type the auto-capture patterns emitted — Decision, Error, Learning,
 * Context — failed validation on the server and was silently coerced to
 * 'observation', so the classification computed here was discarded on store.
 *
 * Run: node --test claude-hooks/tests/auto-capture-types.test.js
 *
 * The valid set below mirrors src/mcp_memory_service/models/ontology.py. It is
 * duplicated rather than imported because these hooks are Node and the
 * ontology is Python; the test asserts membership, so drift in the ontology
 * shows up here as a failure rather than silently at runtime.
 */

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { PATTERNS } = require('../utilities/auto-capture-patterns');

// Base types plus the observation subtypes the hooks use.
const VALID_TYPES = new Set([
    'observation', 'decision', 'learning', 'error', 'pattern',
    'planning', 'ceremony', 'milestone', 'stakeholder',
    'meeting', 'research', 'communication',
    'code_edit', 'file_access', 'search', 'command', 'conversation',
    'conversation_turn', 'session', 'document', 'note', 'reference',
    'user_correction', 'tool_outcome', 'preference_signal',
]);

test('every auto-capture pattern emits a type the ontology accepts', () => {
    assert.ok(PATTERNS && typeof PATTERNS === 'object', 'PATTERNS export missing');
    for (const [name, pattern] of Object.entries(PATTERNS)) {
        assert.ok(
            VALID_TYPES.has(pattern.memoryType),
            `pattern "${name}" emits "${pattern.memoryType}", which the ontology rejects`
        );
    }
});

test('emitted types are canonical (lowercase, no hyphens)', () => {
    for (const [name, pattern] of Object.entries(PATTERNS)) {
        assert.strictEqual(
            pattern.memoryType, pattern.memoryType.toLowerCase(),
            `pattern "${name}" emits a capitalized type`
        );
        assert.ok(
            !pattern.memoryType.includes('-'),
            `pattern "${name}" emits a hyphenated type; custom type names cannot be registered with hyphens before v11.6`
        );
    }
});

test('the force-remember override and session summary send valid types too', () => {
    const files = {
        'core/auto-capture-hook.js': /memoryType:\s*'([^']+)'/g,
        'core/session-end.js': /memoryType:\s*'([^']+)'/g,
    };
    for (const [rel, re] of Object.entries(files)) {
        const src = fs.readFileSync(path.join(__dirname, '..', rel), 'utf8');
        const found = [...src.matchAll(re)].map((m) => m[1]);
        assert.ok(found.length > 0, `no memoryType literal found in ${rel}`);
        for (const type of found) {
            assert.ok(VALID_TYPES.has(type), `${rel} sends "${type}", which the ontology rejects`);
        }
    }
});
