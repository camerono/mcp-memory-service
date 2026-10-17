'use strict';

/**
 * Tests for utilities/config-loader.js (issue #155).
 *
 * Run: node --test claude-hooks/tests/config-loader.test.js
 *
 * Regression guard: hooks must read the user-owned
 * ~/.claude/hooks/config.json when it exists, instead of the bundled copy
 * that ships next to the hook package (which is a read-only, upgrade-volatile
 * plugin cache dir under a Marketplace install).
 */

const { test, afterEach } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { resolveConfigPath, getUserConfigPath } = require('../utilities/config-loader');

const realHomedir = os.homedir;

// A stand-in for a hook module living in core/. The bundled fallback config is
// therefore <hookDir>/../config.json.
const HOOK_DIR = '/opt/plugin-cache/mcp-memory-service/1.0.0/core';
const BUNDLED = path.join(HOOK_DIR, '../config.json');

function useFakeHome() {
    const home = fs.mkdtempSync(path.join(os.tmpdir(), 'mms-hook-home-'));
    os.homedir = () => home;
    return home;
}

afterEach(() => {
    os.homedir = realHomedir;
});

test('getUserConfigPath points at ~/.claude/hooks/config.json', () => {
    const home = useFakeHome();
    assert.strictEqual(
        getUserConfigPath(),
        path.join(home, '.claude', 'hooks', 'config.json')
    );
});

test('prefers the user config when ~/.claude/hooks/config.json exists', () => {
    const home = useFakeHome();
    const userConfig = path.join(home, '.claude', 'hooks', 'config.json');
    fs.mkdirSync(path.dirname(userConfig), { recursive: true });
    fs.writeFileSync(userConfig, '{}');

    assert.strictEqual(resolveConfigPath(HOOK_DIR), userConfig);
});

test('falls back to the bundled config when no user config exists', () => {
    useFakeHome(); // fresh empty home, no .claude/hooks/config.json written
    assert.strictEqual(resolveConfigPath(HOOK_DIR), BUNDLED);
});
