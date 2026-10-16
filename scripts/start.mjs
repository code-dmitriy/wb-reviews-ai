// Запуск: node scripts/start.mjs
// 1) читает .env, 2) импортирует ключи и воркфлоу в n8n, 3) включает «Кнопки менеджера», 4) запускает n8n.
import { spawnSync, spawn } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const N8N = join(ROOT, 'n8n', 'node_modules', 'n8n', 'bin', 'n8n');

const envFile = process.env.ENV_FILE || join(ROOT, '.env');
if (!existsSync(envFile)) {
  console.error('Нет файла .env — скопируйте .env.example в .env и заполните.');
  process.exit(1);
}
const vars = {};
for (const line of readFileSync(envFile, 'utf8').split(/\r?\n/)) {
  const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$/);
  if (m) vars[m[1]] = m[2].replace(/^["']|["']$/g, '');
}
const missing = ['TG_BOT_TOKEN', 'TG_CHAT_ID', 'OPENROUTER_API_KEY'].filter((k) => !vars[k]);
if (missing.length) {
  console.error('В .env не заполнено: ' + missing.join(', '));
  process.exit(1);
}

const env = {
  ...process.env,
  ...vars,
  MODE: vars.MODE || 'demo',
  N8N_USER_FOLDER: join(ROOT, '.n8n-data'),
  N8N_PORT: vars.N8N_PORT || '5678',
  N8N_BLOCK_ENV_ACCESS_IN_NODE: 'false',
  GENERIC_TIMEZONE: 'Europe/Moscow',
  N8N_DIAGNOSTICS_ENABLED: 'false',
  N8N_PERSONALIZATION_ENABLED: 'false',
  N8N_SECURE_COOKIE: 'false',
};

const n8n = (...args) => {
  const r = spawnSync(process.execPath, [N8N, ...args], { env, stdio: ['ignore', 'pipe', 'pipe'], encoding: 'utf8' });
  if (r.status !== 0) {
    console.error(`n8n ${args[0]} завершился с ошибкой:\n${r.stdout}\n${r.stderr}`);
    process.exit(1);
  }
};

// Ключи кладём во временный файл только на время импорта: n8n сам их зашифрует у себя в базе
const credsFile = join(ROOT, '.n8n-data', 'creds.tmp.json');
spawnSync(process.execPath, ['-e', `require('fs').mkdirSync(${JSON.stringify(join(ROOT, '.n8n-data'))}, {recursive: true})`]);
writeFileSync(credsFile, JSON.stringify([
  { id: 'brandTelegram01', name: 'Telegram · бот отзывов MIRA', type: 'telegramApi',
    data: { accessToken: vars.TG_BOT_TOKEN, baseUrl: 'https://api.telegram.org' } },
  { id: 'brandOpenRouter', name: 'OpenRouter', type: 'openRouterApi',
    data: { apiKey: vars.OPENROUTER_API_KEY, url: 'https://openrouter.ai/api/v1' } },
]));
try {
  console.log('→ импорт ключей');
  n8n('import:credentials', `--input=${credsFile}`);
} finally {
  rmSync(credsFile, { force: true });
}

// при повторном запуске опубликованный воркфлоу нельзя перезаписать — сначала снимаем с публикации
spawnSync(process.execPath, [N8N, 'unpublish:workflow', '--id=ReviewButtons001'], { env, stdio: 'ignore' });
console.log('→ импорт воркфлоу');
n8n('import:workflow', '--separate', `--input=${join(ROOT, 'workflows')}`);
console.log('→ включаю «Кнопки менеджера»');
n8n('publish:workflow', '--id=ReviewButtons001');

if (process.argv.includes('--import-only')) process.exit(0);
if (process.argv.includes('--run-drafts')) {
  console.log('→ запускаю «Черновики ответов» без интерфейса');
  const r = spawnSync(process.execPath, [N8N, 'execute', '--id=ReviewReplies001'], { env, stdio: 'inherit' });
  process.exit(r.status ?? 0);
}

console.log(`→ запускаю n8n: http://localhost:${env.N8N_PORT}  (режим: ${env.MODE})`);
const child = spawn(process.execPath, [N8N, 'start'], { env, stdio: 'inherit' });
child.on('exit', (code) => process.exit(code ?? 0));
