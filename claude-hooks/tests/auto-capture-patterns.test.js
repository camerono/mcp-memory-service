'use strict';

/**
 * Behavior tests for auto-capture pattern detection.
 *
 * Run: node --test claude-hooks/tests/auto-capture-patterns.test.js
 *
 * Regression guard for the "error" false-positive bug: cautionary messages
 * that merely contain an error trigger word as a SUBSTRING of a larger word
 * (e.g. "unresolved" contains "resolved") must not be classified as errors.
 */

const { test } = require('node:test');
const assert = require('node:assert');
const { detectPatterns } = require('../utilities/auto-capture-patterns');

// detectPatterns requires content >= 300 chars; pad with neutral filler that
// contains no other pattern trigger words.
const FILLER = ' The situation was written down carefully and the next steps are'
    + ' clearly outlined. We wait for a reply before we continue. Everything'
    + ' else stays as it was for now and gets looked at again later once there'
    + ' is enough time available for that today and tomorrow morning as well.';

test('substring of an error word inside a larger word is not classified as error', () => {
    // "unresolved" contains "resolved" only as a substring.
    const content = 'We looked at the merge state and the state is still unresolved.' + FILLER;
    const result = detectPatterns(content);
    assert.notStrictEqual(result.matchedPattern, 'error',
        `expected not "error", got "${result.matchedPattern}"`);
});

test('a genuine failure message is still classified as error', () => {
    const content = 'While updating the branch the git pull failed because an open merge was in the way.' + FILLER;
    const result = detectPatterns(content);
    assert.strictEqual(result.matchedPattern, 'error',
        `expected "error", got "${result.matchedPattern}"`);
});
