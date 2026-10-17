#!/usr/bin/env node
/**
 * Tests for the allowSelfSignedCerts opt-in gate, centralized in
 * utilities/tls-options.js (applySelfSignedCertsOption) and consumed by:
 *   - utilities/memory-client.js (MemoryClient._applySelfSignedCertsOption)
 *   - core/topic-change.js (queryMemoryService)
 *   - core/memory-retrieval.js (queryMemoryService)
 *   - core/session-end.js (triggerQualityEvaluation, storeSessionMemory)
 *   - utilities/dynamic-context-updater.js (DynamicContextUpdater.queryMemoryService)
 *
 * In every case: rejectUnauthorized must stay unset (verification enabled)
 * unless allowSelfSignedCerts is explicitly true AND the endpoint is https.
 *
 * Uses node:test + node:assert (no external deps).
 * Run: node --test claude-hooks/tests/tls-verification-opt-in.test.js
 */

'use strict';

const { test } = require('node:test');
const assert = require('node:assert');

// Intercepts https.request, capturing every options object it's called with,
// and resolves the caller with a mocked network error so promises settle fast.
function interceptHttpsRequest() {
    const https = require('https');
    const original = https.request;
    const captured = [];
    https.request = function (opts, _cb) {
        captured.push(opts);
        const fakeReq = {
            listeners: {},
            on(event, handler) { this.listeners[event] = handler; return this; },
            write() {},
            end() {
                setImmediate(() => this.listeners.error && this.listeners.error(new Error('mocked')));
            }
        };
        return fakeReq;
    };
    return {
        captured,
        restore() { https.request = original; }
    };
}

test('utilities/tls-options.js: applySelfSignedCertsOption (shared helper)', async (t) => {
    const { applySelfSignedCertsOption } = require('../utilities/tls-options');

    await t.test('default leaves TLS verification enabled', () => {
        const options = {};
        applySelfSignedCertsOption(options, true, false);
        assert.strictEqual(options.rejectUnauthorized, undefined);
    });

    await t.test('true + https disables verification', () => {
        const options = {};
        applySelfSignedCertsOption(options, true, true);
        assert.strictEqual(options.rejectUnauthorized, false);
    });

    await t.test('true + plain http is a no-op', () => {
        const options = {};
        applySelfSignedCertsOption(options, false, true);
        assert.strictEqual(options.rejectUnauthorized, undefined);
    });

    await t.test('logPrefix defaults to [Memory Hook]', () => {
        const originalWarn = console.warn;
        const warnings = [];
        console.warn = (msg) => warnings.push(msg);
        try {
            applySelfSignedCertsOption({}, true, true);
        } finally {
            console.warn = originalWarn;
        }
        assert.ok(warnings[0].startsWith('[Memory Hook]'), 'should use default prefix');
    });

    await t.test('logPrefix is respected when passed', () => {
        const originalWarn = console.warn;
        const warnings = [];
        console.warn = (msg) => warnings.push(msg);
        try {
            applySelfSignedCertsOption({}, true, true, '[Dynamic Context]');
        } finally {
            console.warn = originalWarn;
        }
        assert.ok(warnings[0].startsWith('[Dynamic Context]'), 'should use passed-in prefix');
    });
});

test('memory-client.js: _applySelfSignedCertsOption', async (t) => {
    const { MemoryClient } = require('../utilities/memory-client');

    await t.test('default (no config) leaves TLS verification enabled', () => {
        const client = new MemoryClient({});
        const options = {};
        client._applySelfSignedCertsOption(options, true);
        assert.strictEqual(options.rejectUnauthorized, undefined);
    });

    await t.test('allowSelfSignedCerts=true over https disables verification', () => {
        const client = new MemoryClient({ allowSelfSignedCerts: true });
        const options = {};
        client._applySelfSignedCertsOption(options, true);
        assert.strictEqual(options.rejectUnauthorized, false);
    });

    await t.test('allowSelfSignedCerts=true over plain http is a no-op', () => {
        const client = new MemoryClient({ allowSelfSignedCerts: true });
        const options = {};
        client._applySelfSignedCertsOption(options, false);
        assert.strictEqual(options.rejectUnauthorized, undefined);
    });
});

test('core/topic-change.js: queryMemoryService', async (t) => {
    const { _internal } = require('../core/topic-change');

    await t.test('TLS verification stays enabled by default', async () => {
        const { captured, restore } = interceptHttpsRequest();
        try {
            await _internal.queryMemoryService('https://example.invalid', 'key', 'q', {});
        } catch (_) { /* expected — mocked network error */ }
        restore();
        assert.strictEqual(captured[0].rejectUnauthorized, undefined);
    });

    await t.test('allowSelfSignedCerts=true disables verification', async () => {
        const { captured, restore } = interceptHttpsRequest();
        try {
            await _internal.queryMemoryService('https://example.invalid', 'key', 'q', { allowSelfSignedCerts: true });
        } catch (_) { /* expected */ }
        restore();
        assert.strictEqual(captured[0].rejectUnauthorized, false);
    });
});

test('core/memory-retrieval.js: queryMemoryService', async (t) => {
    const { _internal } = require('../core/memory-retrieval');

    await t.test('TLS verification stays enabled by default', async () => {
        const { captured, restore } = interceptHttpsRequest();
        try {
            await _internal.queryMemoryService('https://example.invalid', 'key', { semanticQuery: 'q' });
        } catch (_) { /* expected */ }
        restore();
        assert.strictEqual(captured[0].rejectUnauthorized, undefined);
    });

    await t.test('allowSelfSignedCerts=true disables verification', async () => {
        const { captured, restore } = interceptHttpsRequest();
        try {
            await _internal.queryMemoryService('https://example.invalid', 'key', { semanticQuery: 'q' }, true);
        } catch (_) { /* expected */ }
        restore();
        assert.strictEqual(captured[0].rejectUnauthorized, false);
    });
});

test('core/session-end.js: triggerQualityEvaluation', async (t) => {
    const { _internal } = require('../core/session-end');

    await t.test('TLS verification stays enabled by default', async () => {
        const { captured, restore } = interceptHttpsRequest();
        try {
            await _internal.triggerQualityEvaluation('https://example.invalid', 'key', 'hash123');
        } catch (_) { /* expected */ }
        restore();
        assert.strictEqual(captured[0].rejectUnauthorized, undefined);
    });

    await t.test('allowSelfSignedCerts=true disables verification', async () => {
        const { captured, restore } = interceptHttpsRequest();
        try {
            await _internal.triggerQualityEvaluation('https://example.invalid', 'key', 'hash123', true);
        } catch (_) { /* expected */ }
        restore();
        assert.strictEqual(captured[0].rejectUnauthorized, false);
    });
});

test('core/session-end.js: storeSessionMemory forwards allowSelfSignedCerts through MemoryClient', async (t) => {
    // storeSessionMemory constructs a real MemoryClient, whose connect() health
    // check is the first thing to hit the network — intercepting https.request
    // there proves the flag actually reaches MemoryClient, not just that
    // storeSessionMemory's own signature accepts it.
    const { _internal } = require('../core/session-end');

    await t.test('default omits allowSelfSignedCerts (TLS verification enabled)', async () => {
        const { captured, restore } = interceptHttpsRequest();
        try {
            await _internal.storeSessionMemory(
                'https://example.invalid', 'key', 'content',
                { name: 'p', frameworks: [] }, { topics: [], confidence: 0.5 }
            );
        } catch (_) { /* expected — mocked network error */ }
        restore();
        assert.strictEqual(captured[0].rejectUnauthorized, undefined);
    });

    await t.test('explicit true disables TLS verification', async () => {
        const { captured, restore } = interceptHttpsRequest();
        try {
            await _internal.storeSessionMemory(
                'https://example.invalid', 'key', 'content',
                { name: 'p', frameworks: [] }, { topics: [], confidence: 0.5 }, true
            );
        } catch (_) { /* expected */ }
        restore();
        assert.strictEqual(captured[0].rejectUnauthorized, false);
    });
});

test('utilities/dynamic-context-updater.js: queryMemoryService', async (t) => {
    const { DynamicContextUpdater } = require('../utilities/dynamic-context-updater');
    const updater = new DynamicContextUpdater();

    await t.test('TLS verification stays enabled by default', async () => {
        const { captured, restore } = interceptHttpsRequest();
        try {
            await updater.queryMemoryService('https://example.invalid', 'key', 'q', {});
        } catch (_) { /* expected */ }
        restore();
        assert.strictEqual(captured[0].rejectUnauthorized, undefined);
    });

    await t.test('allowSelfSignedCerts=true disables verification', async () => {
        const { captured, restore } = interceptHttpsRequest();
        try {
            await updater.queryMemoryService('https://example.invalid', 'key', 'q', { allowSelfSignedCerts: true });
        } catch (_) { /* expected */ }
        restore();
        assert.strictEqual(captured[0].rejectUnauthorized, false);
    });
});
