/**
 * Shared TLS verification opt-in gate.
 *
 * Centralizes the allowSelfSignedCerts check that was previously duplicated
 * verbatim across memory-client.js, memory-retrieval.js, topic-change.js,
 * session-end.js, and dynamic-context-updater.js — one place to change the
 * warning wording or gating logic instead of five.
 */

'use strict';

/**
 * Mutates requestOptions in place, setting rejectUnauthorized = false only
 * when isHttps is true AND allowSelfSignedCerts was explicitly opted into.
 * Warns every time it's actually used — this disables certificate
 * validation and is vulnerable to MITM, so it should never be silent.
 *
 * @param {object} requestOptions - options object passed to https.request
 * @param {boolean} isHttps
 * @param {boolean} allowSelfSignedCerts
 * @param {string} [logPrefix='[Memory Hook]'] - matches each caller's existing log style
 */
function applySelfSignedCertsOption(requestOptions, isHttps, allowSelfSignedCerts, logPrefix = '[Memory Hook]') {
    if (isHttps && allowSelfSignedCerts) {
        requestOptions.rejectUnauthorized = false;
        console.warn(
            `${logPrefix} TLS certificate validation DISABLED ` +
            '(allowSelfSignedCerts=true). This leaves the hook vulnerable to MITM — ' +
            'use only for local development with self-signed certs.'
        );
    }
}

module.exports = { applySelfSignedCertsOption };
