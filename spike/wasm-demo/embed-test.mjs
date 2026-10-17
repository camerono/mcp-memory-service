// Sanity test: embed 3 sentences with LOCAL model files only, cosine search
import { env, pipeline } from '@huggingface/transformers';

env.localModelPath = './models';
env.allowRemoteModels = false;   // nothing may load from huggingface.co

const t0 = Date.now();
const embed = await pipeline('feature-extraction', 'Xenova/all-MiniLM-L6-v2', { dtype: 'q8' });
console.log('pipeline loaded in', Date.now() - t0, 'ms (local files only)');

const memories = [
  'The database migration failed because of a missing WAL pragma',
  'I love hiking in the Swiss Alps every summer',
  'OAuth tokens must be rotated every 90 days per security policy',
];
const t1 = Date.now();
const out = await embed(memories, { pooling: 'mean', normalize: true });
console.log('embedded 3 sentences in', Date.now() - t1, 'ms, dims:', out.dims);

const vecs = out.tolist();
const cos = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0); // normalized -> dot = cosine

const query = 'security credentials expiring';
const qv = (await embed([query], { pooling: 'mean', normalize: true })).tolist()[0];
const ranked = memories.map((m, i) => [cos(qv, vecs[i]), m]).sort((a, b) => b[0] - a[0]);
console.log('query:', query);
ranked.forEach(([s, m]) => console.log(' ', s.toFixed(4), m.slice(0, 60)));

const pass = ranked[0][1].includes('OAuth');
console.log(pass ? 'PASS: semantic search returns correct top hit' : 'FAIL: wrong top hit');
