// Быстрая проверка модели без n8n: node scripts/probe_model.mjs demo-01 demo-05
import { readFileSync } from 'node:fs';
const v = {};
for (const l of readFileSync('.env', 'utf8').split(/\r?\n/)) { const m = l.match(/^\s*([A-Z_]+)\s*=\s*(.*?)\s*$/); if (m) v[m[1]] = m[2].replace(/^["']|["']$/g, ''); }
eval(readFileSync('src/shared.js', 'utf8').replace(/^const /gm, 'var ').replace(/^function (\w+)/gm, 'globalThis.$1 = function $1'));
const system = readFileSync('prompts/reply_system.md', 'utf8');
const demo = JSON.parse(readFileSync('data/demo_reviews.json', 'utf8')).data.feedbacks;
const model = process.env.MODEL || v.OPENROUTER_MODEL || 'google/gemma-4-31b-it:free';
for (const id of process.argv.slice(2)) {
  const r = normalizeFeedback(demo.find((f) => f.id === id));
  const t0 = Date.now();
  const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${v.OPENROUTER_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, temperature: 0.7, max_tokens: Number(process.env.MAXTOK || 900), messages: [{ role: 'system', content: system }, { role: 'user', content: buildPrompt(r) }] }),
  });
  const j = await res.json();
  if (!res.ok || !j.choices) { console.log(id, res.status, JSON.stringify(j).slice(0, 300)); continue; }
  console.log(`\n=== ${id} (${r.rating}★, ${((Date.now() - t0) / 1000).toFixed(1)} c, ${j.model})\n«${r.text.slice(0, 90)}»`);
  const msg = j.choices[0].message; if (process.env.RAW) console.log("RAW content:", JSON.stringify(msg.content).slice(0, 600), "| reasoning len:", (msg.reasoning || "").length, "| finish:", j.choices[0].finish_reason);
  console.log(parseAi(msg.content));
}
