"""Собирает воркфлоу n8n из промпта, демо-данных и общих JS-функций.

Запуск: python build.py  ->  workflows/*.json
"""
import json
import uuid
from pathlib import Path

ROOT = Path(__file__).parent
SHARED_JS = (ROOT / "src" / "shared.js").read_text(encoding="utf-8")
SYSTEM_PROMPT = (ROOT / "prompts" / "reply_system.md").read_text(encoding="utf-8").strip()
DEMO = json.loads((ROOT / "data" / "demo_reviews.json").read_text(encoding="utf-8"))
DEMO.pop("_comment", None)

TG_CRED = {"telegramApi": {"id": "brandTelegram01", "name": "Telegram · бот отзывов MIRA"}}
OR_CRED = {"openRouterApi": {"id": "brandOpenRouter", "name": "OpenRouter"}}
MODEL = "={{ $env.OPENROUTER_MODEL || 'nvidia/nemotron-3-ultra-550b-a55b:free' }}"
FALLBACK_MODEL = "={{ $env.OPENROUTER_FALLBACK_MODEL || 'nvidia/nemotron-3-ultra-550b-a55b:free' }}"
IS_WB = "={{ $env.MODE === 'wb' }}"
WB_AUTH = {"parameters": [{"name": "Authorization", "value": "={{ $env.WB_API_TOKEN }}"}]}


def node(name, type_, version, pos, params, **extra):
    n = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"wb-reviews/{name}")),
        "name": name,
        "type": type_,
        "typeVersion": version,
        "position": list(pos),
        "parameters": params,
    }
    n.update(extra)
    return n


def code(name, pos, body, each=False, **extra):
    params = {"jsCode": SHARED_JS + "\n// ---\n" + body.strip() + "\n"}
    if each:
        params["mode"] = "runOnceForEachItem"
    return node(name, "n8n-nodes-base.code", 2, pos, params, **extra)


def note(name, pos, text, w=340, h=200, color=7):
    return node(name, "n8n-nodes-base.stickyNote", 1, pos,
                {"content": text, "width": w, "height": h, "color": color})


def if_true(name, pos, expr):
    return node(name, "n8n-nodes-base.if", 2.2, pos, {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, name)),
                "leftValue": expr,
                "rightValue": "",
                "operator": {"type": "boolean", "operation": "true", "singleValue": True},
            }],
            "combinator": "and",
        },
        "options": {},
    })


def llm_chain(name, pos, text_expr):
    return node(name, "@n8n/n8n-nodes-langchain.chainLlm", 1.9, pos, {
        "promptType": "define",
        "text": text_expr,
        "hasOutputParser": False,
        "messages": {"messageValues": [{"type": "SystemMessagePromptTemplate", "message": SYSTEM_PROMPT}]},
        "batching": {"batchSize": 1},
    }, retryOnFail=True, maxTries=3, waitBetweenTries=4000)


def model(name, pos, model_expr=MODEL):
    return node(name, "@n8n/n8n-nodes-langchain.lmChatOpenRouter", 1, pos, {
        "model": model_expr,
        "options": {"temperature": 0.7, "maxTokens": 4000},
    }, credentials=OR_CRED)


def keyboard(id_expr):
    return {"rows": [{"row": {"buttons": [
        {"text": "✅ Опубликовать", "additionalFields": {"callback_data": f"=pub:{id_expr}"}},
        {"text": "🔄 Переписать", "additionalFields": {"callback_data": f"=redo:{id_expr}"}},
    ]}}]}


def tg_edit(name, pos, text_expr, with_keyboard, src):
    params = {
        "operation": "editMessageText",
        "messageType": "message",
        "chatId": f"={{{{ $('{src}').item.json.chatId }}}}",
        "messageId": f"={{{{ $('{src}').item.json.messageId }}}}",
        "text": text_expr,
        "replyMarkup": "inlineKeyboard" if with_keyboard else "none",
        "additionalFields": {"parse_mode": "HTML", "disable_web_page_preview": True},
    }
    if with_keyboard:
        params["inlineKeyboard"] = keyboard(f"{{{{ $('{src}').item.json.r.id }}}}")
    return node(name, "n8n-nodes-base.telegram", 1.2, pos, params, credentials=TG_CRED)


def tg_answer(name, pos, text):
    return node(name, "n8n-nodes-base.telegram", 1.2, pos, {
        "resource": "callback",
        "operation": "answerQuery",
        "queryId": "={{ $json.queryId }}",
        "additionalFields": {"text": text},
    }, credentials=TG_CRED)


def connect(pairs):
    """pairs: (from, to) | (from, to, output_index) | (from, to, 0, 'ai_languageModel', input_index)"""
    conns = {}
    for p in pairs:
        src, dst = p[0], p[1]
        out = p[2] if len(p) > 2 else 0
        kind = p[3] if len(p) > 3 else "main"
        slots = conns.setdefault(src, {}).setdefault(kind, [])
        while len(slots) <= out:
            slots.append([])
        slots[out].append({"node": dst, "type": kind, "index": p[4] if len(p) > 4 else 0})
    return conns


def workflow(id_, name, nodes, pairs, settings=None):
    return {
        "id": id_,
        "name": name,
        "nodes": nodes,
        "connections": connect(pairs),
        "settings": {"executionOrder": "v1", **(settings or {})},
        "pinData": {},
        "active": False,
        "tags": [],
    }


# ---------------------------------------------------------------- 1. Черновики ответов
W1 = [
    note("Описание", (-60, -380), (
        "## Черновики ответов на отзывы WB\n"
        "Берёт неотвеченные отзывы, пишет ответ под каждый отзыв в тоне MIRA "
        "и присылает менеджеру в Telegram с кнопками **Опубликовать / Переписать**.\n\n"
        "**MODE=demo** — обезличенные демо-отзывы в формате API WB.\n"
        "**MODE=wb** — официальный API продавца, нужен токен с доступом «Вопросы и отзывы»."
    ), w=520, h=230, color=4),
    node("Запуск вручную", "n8n-nodes-base.manualTrigger", 1, (0, 0), {}),
    node("Каждые 30 минут", "n8n-nodes-base.scheduleTrigger", 1.2, (0, 200),
         {"rule": {"interval": [{"field": "minutes", "minutesInterval": 30}]}}),
    if_true("Боевой режим?", (240, 100), IS_WB),
    node("WB API: неотвеченные отзывы", "n8n-nodes-base.httpRequest", 4.2, (500, 0), {
        "url": "https://feedbacks-api.wildberries.ru/api/v1/feedbacks",
        "sendQuery": True,
        "queryParameters": {"parameters": [
            {"name": "isAnswered", "value": "false"},
            {"name": "take", "value": "30"},
            {"name": "skip", "value": "0"},
            {"name": "order", "value": "dateDesc"},
        ]},
        "sendHeaders": True,
        "headerParameters": WB_AUTH,
        "options": {},
    }),
    code("Демо: отзывы MIRA", (500, 200),
         "return [{ json: " + json.dumps(DEMO, ensure_ascii=False) + " }];"),
    code("Разбить на отзывы", (760, 100), """
const out = [];
for (const item of $input.all()) {
  for (const f of item.json.data?.feedbacks || []) {
    const r = normalizeFeedback(f);
    out.push({ json: { ...r, prompt: buildPrompt(r) } });
  }
}
return out;
"""),
    node("Сколько отзывов", "n8n-nodes-base.limit", 1, (980, 100),
         {"maxItems": "={{ Number($env.REVIEWS_LIMIT) || 30 }}"}),
    llm_chain("Ответ в стиле MIRA", (1420, 100), "={{ $json.prompt }}"),
    node("По одному отзыву", "n8n-nodes-base.splitInBatches", 3, (1180, 100), {"options": {}}),
    model("OpenRouter · Nemotron", (1420, 320)),
    code("Разобрать ответ ИИ", (1700, 100), """
const r = $('Разбить на отзывы').item.json;
const ai = parseAi($json.text);
if (!ai.reply) throw new Error(`Модель вернула пустой ответ на отзыв ${r.id}`);
return { json: { ...r, ...ai, card: buildCard(r, ai, 1) } };
""", each=True),
    node("Карточка менеджеру", "n8n-nodes-base.telegram", 1.2, (1940, 100), {
        "chatId": "={{ $env.TG_CHAT_ID }}",
        "text": "={{ $json.card }}",
        "replyMarkup": "inlineKeyboard",
        "inlineKeyboard": keyboard("{{ $json.id }}"),
        "additionalFields": {"parse_mode": "HTML", "disable_web_page_preview": True, "appendAttribution": False},
    }, credentials=TG_CRED),
]
W1_PAIRS = [
    ("Запуск вручную", "Боевой режим?"),
    ("Каждые 30 минут", "Боевой режим?"),
    ("Боевой режим?", "WB API: неотвеченные отзывы", 0),
    ("Боевой режим?", "Демо: отзывы MIRA", 1),
    ("WB API: неотвеченные отзывы", "Разбить на отзывы"),
    ("Демо: отзывы MIRA", "Разбить на отзывы"),
    ("Разбить на отзывы", "Сколько отзывов"),
    ("Сколько отзывов", "По одному отзыву"),
    ("По одному отзыву", "Ответ в стиле MIRA", 1),
    ("OpenRouter · Nemotron", "Ответ в стиле MIRA", 0, "ai_languageModel"),
    ("Ответ в стиле MIRA", "Разобрать ответ ИИ"),
    ("Разобрать ответ ИИ", "Карточка менеджеру"),
    ("Карточка менеджеру", "По одному отзыву"),
]

# ---------------------------------------------------------------- 2. Кнопки менеджера
P = "Разобрать нажатия"
W2 = [
    note("Описание", (-60, -420), (
        "## Кнопки менеджера\n"
        "Каждые 5 секунд спрашивает Telegram, какие кнопки нажали (getUpdates — "
        "работает без публичного адреса и вебхуков).\n\n"
        "**Опубликовать** → в боевом режиме ответ уходит в WB через API, карточка помечается ✅.\n"
        "**Переписать** → модель пишет новый вариант с другим акцентом, карточка обновляется.\n\n"
        "Нажатия принимаются только из чата TG_CHAT_ID."
    ), w=560, h=250, color=4),
    node("Каждые 5 секунд", "n8n-nodes-base.scheduleTrigger", 1.2, (0, 100),
         {"rule": {"interval": [{"field": "seconds", "secondsInterval": 5}]}}),
    node("Настройки", "n8n-nodes-base.set", 3.4, (200, 100), {
        "mode": "manual",
        "assignments": {"assignments": [
            {"id": "cfg-chat", "name": "chatId", "value": "={{ $env.TG_CHAT_ID }}", "type": "string"},
            {"id": "cfg-mode", "name": "mode", "value": "={{ $env.MODE || 'demo' }}", "type": "string"},
        ]},
        "options": {},
    }),
    node("Telegram: новые нажатия", "n8n-nodes-base.httpRequest", 4.2, (400, 100), {
        "url": "=https://api.telegram.org/bot{{ $env.TG_BOT_TOKEN }}/getUpdates",
        "sendQuery": True,
        "queryParameters": {"parameters": [
            {"name": "timeout", "value": "0"},
            {"name": "allowed_updates", "value": "[\"callback_query\"]"},
        ]},
        "options": {"timeout": 4000},
    }, onError="continueRegularOutput"),
    code(P, (600, 100), """
const updates = $input.first().json.result || [];
if (!updates.length) return [];
const offset = updates[updates.length - 1].update_id + 1;
const cfg = $('Настройки').first().json;
const allowedChat = String(cfg.chatId);
const out = [];
for (const u of updates) {
  const q = u.callback_query;
  if (!q || String(q.message?.chat?.id) !== allowedChat) continue;
  const [action] = String(q.data || '').split(':');
  const { r, ai, variant } = parseCard(q.message.text || '');
  const now = new Date().toLocaleString('ru-RU', { timeZone: 'Europe/Moscow', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  const mode = cfg.mode === 'wb' ? 'отправлено в WB' : 'демо-режим, в боевом уходит в WB по API';
  out.push({ json: {
    action, offset, r, ai, variant,
    queryId: q.id, chatId: q.message.chat.id, messageId: q.message.message_id,
    doneCard: buildCard(r, ai, variant).replace(/\\n\\n<code>ID:/, `\\n\\n✅ <b>Опубликовано</b> · ${now} (${mode})\\n\\n<code>ID:`),
    redoPrompt: buildPrompt(r, ai.reply),
  }});
}
return out.length ? out : [{ json: { action: 'skip', offset } }];
"""),
    node("Telegram: отметить прочитанным", "n8n-nodes-base.httpRequest", 4.2, (840, -100), {
        "url": "=https://api.telegram.org/bot{{ $env.TG_BOT_TOKEN }}/getUpdates",
        "sendQuery": True,
        "queryParameters": {"parameters": [
            {"name": "offset", "value": "={{ $json.offset }}"},
            {"name": "timeout", "value": "0"},
        ]},
        "options": {"timeout": 4000},
    }, executeOnce=True, onError="continueRegularOutput"),
    node("Что нажали?", "n8n-nodes-base.switch", 3.2, (840, 160), {
        "rules": {"values": [
            {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                    "conditions": [{"id": str(uuid.uuid4()), "leftValue": "={{ $json.action }}", "rightValue": action,
                                    "operator": {"type": "string", "operation": "equals"}}],
                    "combinator": "and",
                },
                "renameOutput": True,
                "outputKey": label,
            }
            for action, label in (("pub", "Опубликовать"), ("redo", "Переписать"))
        ]},
        "options": {},
    }),
    # --- Опубликовать
    tg_answer("Ок: публикую", (960, 40), "Публикую ответ…"),
    if_true("Боевой режим?", (1180, 40), IS_WB),
    node("WB API: опубликовать ответ", "n8n-nodes-base.httpRequest", 4.2, (1420, -60), {
        "method": "POST",
        "url": "https://feedbacks-api.wildberries.ru/api/v1/feedbacks/answer",
        "sendHeaders": True,
        "headerParameters": WB_AUTH,
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": f"={{{{ JSON.stringify({{ id: $('{P}').item.json.r.id, text: $('{P}').item.json.ai.reply }}) }}}}",
        "options": {},
    }),
    tg_edit("Карточка: опубликовано", (1680, 40), f"={{{{ $('{P}').item.json.doneCard }}}}", False, P),
    # --- Переписать
    tg_answer("Ок: переписываю", (960, 300), "Пишу новый вариант…"),
    llm_chain("Новый вариант ответа", (1180, 300), f"={{{{ $('{P}').item.json.redoPrompt }}}}"),
    model("OpenRouter · Nemotron ", (1180, 520)),
    code("Собрать новую карточку", (1460, 300), f"""
const p = $('{P}').item.json;
const ai = parseAi($json.text);
if (!ai.reply) throw new Error('Модель вернула пустой ответ');
return {{ json: {{ card: buildCard(p.r, ai, p.variant + 1) }} }};
""", each=True),
    tg_edit("Карточка: новый вариант", (1680, 300), "={{ $json.card }}", True, P),
]
W2_PAIRS = [
    ("Каждые 5 секунд", "Настройки"),
    ("Настройки", "Telegram: новые нажатия"),
    ("Telegram: новые нажатия", P),
    (P, "Telegram: отметить прочитанным"),
    (P, "Что нажали?"),
    ("Что нажали?", "Ок: публикую", 0),
    ("Что нажали?", "Ок: переписываю", 1),
    ("Ок: публикую", "Боевой режим?"),
    ("Боевой режим?", "WB API: опубликовать ответ", 0),
    ("Боевой режим?", "Карточка: опубликовано", 1),
    ("WB API: опубликовать ответ", "Карточка: опубликовано"),
    ("Ок: переписываю", "Новый вариант ответа"),
    ("OpenRouter · Nemotron ", "Новый вариант ответа", 0, "ai_languageModel"),
    ("Новый вариант ответа", "Собрать новую карточку"),
    ("Собрать новую карточку", "Карточка: новый вариант"),
]

out = ROOT / "workflows"
out.mkdir(exist_ok=True)
for fname, wf in (
    ("1_reply_drafts.json", workflow("ReviewReplies001", "MIRA · Черновики ответов на отзывы", W1, W1_PAIRS)),
    ("2_manager_buttons.json", workflow("ReviewButtons001", "MIRA · Кнопки менеджера", W2, W2_PAIRS,
                                        {"saveDataSuccessExecution": "none", "saveManualExecutions": True})),
):
    (out / fname).write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ok", fname, len(wf["nodes"]), "nodes")
