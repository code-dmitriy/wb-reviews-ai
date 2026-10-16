// Общие функции для Code-нод n8n. Сборщик (build.py) вставляет этот файл в начало каждой Code-ноды.

const CATEGORY_ICON = {
  'пересорт': '🚨', 'брак': '🚨', 'комплектация': '🚨', 'размер': '📏',
  'цена': '💰', 'доставка': '🚚', 'положительный': '💚', 'другое': '💬',
};

const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// Отзыв из API WB (или демо-набора) -> плоский объект
function normalizeFeedback(f) {
  const d = f.productDetails || {};
  const parts = [f.text, f.pros && `Достоинства: ${f.pros}`, f.cons && `Недостатки: ${f.cons}`].filter(Boolean);
  return {
    id: String(f.id),
    name: f.userName || 'Покупатель',
    rating: Number(f.productValuation) || 0,
    text: parts.join('\n') || '(без текста, только оценка)',
    product: d.productName || 'Товар',
    size: d.size || '',
    color: d.color || '',
    status: f.orderStatus || '',
    date: f.createdDate ? new Date(f.createdDate).toLocaleDateString('ru-RU') : '',
  };
}

// Текст запроса к модели. Фигурные скобки здесь безопасны: это значение переменной, а не шаблон.
function buildPrompt(r, previousDraft) {
  let p = `Отзыв покупательницы на Wildberries.
Товар: ${r.product}
Оценка: ${r.rating} из 5
Имя: ${r.name}
Размер и цвет: ${[r.size, r.color].filter(Boolean).join(', ') || 'не указаны'}
Статус заказа: ${r.status || 'не указан'}
Текст отзыва: «${r.text}»
`;
  if (previousDraft) {
    p += `
Предыдущий черновик ответа не понравился менеджеру:
«${previousDraft}»
Напиши новый вариант: другими словами и с другим акцентом.
`;
  }
  p += `
Верни строго JSON вида:
{"category": "размер", "urgent": false, "team_note": "", "reply": "текст ответа"}`;
  return p;
}

// Достаёт JSON из ответа модели, даже если она обернула его в ```json или добавила текст вокруг
function parseAi(raw) {
  const text = String(raw ?? '').trim();
  const m = text.match(/\{[\s\S]*\}/);
  const body = m ? m[0] : text;
  let j;
  try {
    // модели иногда вставляют в строки настоящие переносы — экранируем их и пробуем ещё раз
    try { j = JSON.parse(body); } catch (e) { j = JSON.parse(body.replace(/\r?\n/g, '\\n')); }
    let reply = String(j.reply || '').trim();
    // подпись бренда ставим сами, модели иногда её забывают
    if (reply && !/MIRA[!.]?\s*$/.test(reply)) reply += '\nКоманда MIRA';
    return {
      category: String(j.category || 'другое').toLowerCase(),
      urgent: j.urgent === true || j.urgent === 'true',
      team_note: String(j.team_note || '').trim(),
      reply,
    };
  } catch (e) {
    return { category: 'другое', urgent: false, team_note: '', reply: text };
  }
}

// Карточка отзыва для менеджера в Telegram (HTML)
function buildCard(r, ai, variant) {
  const stars = '⭐'.repeat(r.rating) + '☆'.repeat(Math.max(0, 5 - r.rating));
  const icon = CATEGORY_ICON[ai.category] || '💬';
  const lines = [
    `${stars} <b>${r.rating}/5</b> · ${icon} ${esc(ai.category)}`,
    `<b>${esc(r.product)}</b>`,
    esc([r.size, r.color, r.status].filter(Boolean).join(' · ')),
    `👤 ${esc(r.name)}${r.date ? ' · ' + esc(r.date) : ''}`,
    '',
    `💬 <i>${esc(r.text)}</i>`,
    '',
    '✍️ <b>Черновик ответа:</b>',
    `<blockquote>${esc(ai.reply)}</blockquote>`,
  ];
  if (ai.team_note) lines.push('', `⚠️ <b>Команде:</b> ${esc(ai.team_note)}`);
  if (variant > 1) lines.push('', `🔄 Вариант ${variant}`);
  lines.push('', `<code>ID: ${esc(r.id)}</code>`);
  return lines.join('\n');
}

// Обратная операция: из текста сообщения (Telegram отдаёт его без HTML) восстанавливаем отзыв и черновик
function parseCard(t) {
  const lines = t.split('\n');
  const between = (a, b) => {
    const i = t.indexOf(a);
    if (i < 0) return '';
    const from = i + a.length;
    const ends = b.map((x) => t.indexOf(x, from)).filter((x) => x >= 0);
    return t.slice(from, ends.length ? Math.min(...ends) : undefined).trim();
  };
  const [size = '', color = '', status = ''] = (lines[2] || '').split(' · ');
  const who = (lines[3] || '').replace(/^👤\s*/, '').split(' · ');
  const r = {
    id: (t.match(/ID: (\S+)\s*$/) || [])[1] || '',
    rating: Number((lines[0].match(/(\d)\/5/) || [])[1]) || 0,
    product: lines[1] || '',
    size, color, status,
    name: who[0] || 'Покупатель',
    date: who[1] || '',
    text: between('\n\n💬 ', ['\n\n✍️ Черновик ответа:']),
  };
  const ai = {
    category: (lines[0].split(' · ')[1] || '').replace(/^\S+\s*/, '') || 'другое',
    reply: between('Черновик ответа:\n', ['\n\n⚠️ Команде:', '\n\n🔄 Вариант', '\n\nID:']),
    team_note: between('⚠️ Команде: ', ['\n\n🔄 Вариант', '\n\nID:']),
  };
  const variant = Number((t.match(/🔄 Вариант (\d+)/) || [])[1]) || 1;
  return { r, ai, variant };
}
