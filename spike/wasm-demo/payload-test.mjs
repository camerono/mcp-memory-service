// Measure exactly which assets the prototype fetches and their sizes
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join } from 'node:path';
import puppeteer from 'puppeteer-core';

const root = new URL('.', import.meta.url).pathname;
const mime = { '.html': 'text/html', '.mjs': 'text/javascript', '.js': 'text/javascript',
  '.wasm': 'application/wasm', '.json': 'application/json', '.onnx': 'application/octet-stream' };
const served = new Map();
const server = createServer(async (req, res) => {
  try {
    const rel = decodeURIComponent(req.url.split('?')[0]);
    const path = join(root, rel);
    const p = (await stat(path)).isDirectory() ? join(path, 'index.html') : path;
    const body = await readFile(p);
    served.set(rel, body.length);
    res.writeHead(200, { 'Content-Type': mime[extname(p)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end('nf'); }
});
await new Promise((r) => server.listen(8788, r));

const browser = await puppeteer.launch({ executablePath: process.env.CHROME_BIN, headless: 'new' });
const page = await browser.newPage();
const t0 = Date.now();
await page.goto('http://localhost:8788/index.html', { waitUntil: 'networkidle0', timeout: 120000 });
await page.waitForFunction(() => document.getElementById('log').textContent.match(/SELFTEST-(PASS|FAIL)|FATAL/), { timeout: 120000 });
const verdict = await page.evaluate(() => document.getElementById('log').textContent.match(/SELFTEST-\w+/)?.[0]);
console.log('verdict:', verdict, '| wall time to interactive+selftest (localhost):', Date.now() - t0, 'ms');
let total = 0;
for (const [url, size] of [...served].sort((a, b) => b[1] - a[1])) {
  total += size;
  console.log(' ', (size / 1024 / 1024).toFixed(3).padStart(8), 'MB ', url);
}
console.log('TOTAL first-load payload:', (total / 1024 / 1024).toFixed(2), 'MB (uncompressed)');
console.log('over-25MiB files:', [...served].filter(([, s]) => s > 25 * 1024 * 1024).map(([u]) => u).join(',') || 'NONE');
await browser.close(); server.close(); process.exit(0);
