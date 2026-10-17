// Headless verification: serve dir statically, load index.html in chromium, capture console
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join } from 'node:path';
import puppeteer from 'puppeteer-core';

const root = new URL('.', import.meta.url).pathname;
const mime = { '.html': 'text/html', '.mjs': 'text/javascript', '.js': 'text/javascript',
  '.wasm': 'application/wasm', '.json': 'application/json', '.onnx': 'application/octet-stream',
  '.txt': 'text/plain' };

const server = createServer(async (req, res) => {
  try {
    const path = join(root, decodeURIComponent(req.url.split('?')[0]));
    const p = (await stat(path)).isDirectory() ? join(path, 'index.html') : path;
    const body = await readFile(p);
    res.writeHead(200, { 'Content-Type': mime[extname(p)] || 'application/octet-stream',
      'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'require-corp' });
    res.end(body);
  } catch { res.writeHead(404); res.end('nf'); }
});
await new Promise((r) => server.listen(8787, r));
console.log('server on :8787');

const CHROME = process.env.CHROME_BIN;
const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new' });
const page = await browser.newPage();
const lines = [];
page.on('console', (m) => lines.push(m.text()));
page.on('response', (r) => { if (r.status() >= 400) lines.push('HTTP ' + r.status() + ' ' + r.url()); });
page.on('pageerror', (e) => lines.push('PAGEERROR ' + e.message));
const reqs = [];
page.on('request', (r) => { if (!r.url().startsWith('http://localhost:8787')) reqs.push(r.url()); });

await page.goto('http://localhost:8787/sqlite-only.html', { waitUntil: 'networkidle0', timeout: 120000 });
// wait until selftest verdict appears
try {
  await page.waitForFunction(
    () => document.getElementById('log').textContent.match(/SELFTEST-(PASS|FAIL)|FATAL/),
    { timeout: 120000 });
} catch { lines.push('TIMEOUT waiting for selftest'); }
console.log('--- console output ---');
lines.forEach((l) => console.log(l.slice(0, 200)));
console.log('--- external (non-localhost) requests:', reqs.length ? reqs.join(', ') : 'NONE');
await browser.close();
server.close();
process.exit(0);
