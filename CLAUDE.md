# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Telegram-бот на **aiogram 3.x** для `status.claude.com`. Источник уведомлений — RSS history feed
`https://status.claude.com/history.rss`. JSON API Statuspage (`/api/v2/...`) нельзя убирать: он
используется для enrichment уведомлений (impact/status/иконка/shortlink) и для команды `/test`.

## Commands

```bash
pip install -r requirements.txt
cp .env.example .env            # впишите BOT_TOKEN, при желании CHAT_ID

python main.py
pytest -v
pytest tests/test_differ.py::test_poller_edits_non_resolved_update

docker build -t cc-status-bot .
docker run -d --restart unless-stopped --env-file .env -v "$(pwd)/data:/app/data" \
  --name cc_status_bot cc-status-bot
```

Нет линтера/форматтера в конфиге — стиль поддерживается вручную (`from __future__ import annotations`,
типизация, короткие русские докстринги/комментарии там, где они реально помогают).

## Architecture

`main.py` поднимает два concurrent asyncio-потока на общей `aiohttp.ClientSession`:
1. `dp.start_polling` — Telegram-команды (`/start`, `/test`) из `app/handlers.py`.
2. `run_poller` — фоновый RSS poller из `app/poller.py`.

Основной конвейер уведомлений (`poll_once` в `poller.py`):

`fetch_rss()` → `diff()` → (если есть события) `fetch()` для JSON enrichment → `format_event()` → `send_message`/`edit_message_text` → `save_state()`.

- **`status_client.py`** — парсит RSS (`RssItem`, `parse_rss_items` — чистая, без сети) и держит три эндпоинта Statuspage: `fetch_summary` (summary.json), `fetch_details` (incidents.json + scheduled-maintenances.json) и `fetch` (всё параллельно через `asyncio.gather`). `RssItem.incident_id` извлекается regex'ом из URL — это ключ связи RSS↔JSON.
- **`differ.py`** — чистая RSS-логика без сети и Telegram. Возвращает действия `send`, `edit`, `send_resolved`. JSON здесь не участвует — события рождаются только из RSS.
- **`formatter.py`** — текст берёт из RSS, impact/status/icon/shortlink берёт из JSON incident, найденного по `incident_id`. Enrichment best-effort: при ошибке JSON (`_fetch_enrichment` → `None`) сообщение уходит RSS-only.
- **`poller.py`** — non-resolved RSS updates редактируют сохранённый `message_id` (с fallback на новый send, если edit не удался); `Resolved` всегда шлёт новое зелёное сообщение. `_SEND_DELAY` + обработка `TelegramRetryAfter` защищают от rate-limit.
- **`state.py`** — атомарно (`tempfile` + `os.replace`) хранит `data/state.json`; битый/отсутствующий файл → пустое состояние.

## Formatter invariants (легко сломать)

- **RSS владеет переходом в `resolved`** — JSON-статус инцидента может кратко отставать. `_json_or_rss_status` принудительно возвращает `resolved`, если так сказал RSS, игнорируя JSON.
- **`/test` переопределяет «зелёный» индикатор** — Statuspage иногда держит общий indicator `none`, пока инцидент ещё не задел компоненты. `_overall_header` при наличии активных инцидентов поднимает заголовок до minor/major/critical, чтобы не показывать ложное «All Systems Operational».

## State invariants

Текущий контракт state: `rss_initialized: true` и `rss_items[guid]` с `pub_date`,
`message_id`, `resolved_message_id`. Старые ключи `incidents`, `maintenances`, `components`
могут оставаться в файле как legacy, но не должны создавать Telegram-события.

Первый RSS-запуск засевает ленту молча и **в чат `CHAT_ID` ничего не шлёт**. Это важно при
миграции со старого JSON-state: наличие `initialized: true` без `rss_initialized` не должно
разослать всю RSS-историю. Без `CHAT_ID` бот работает в command-only режиме (события логируются
с warning, но не шлются).

Служебный пинг «Monitoring started» уходит **админу (`ADMIN_ID`) в личку при каждом старте
процесса** — он живёт в `run_poller` (до цикла `while`), а не в ветке первого запуска, и не
зависит от `data/state.json`. Поэтому потеря state не приводит к спаму в группу. Отправка
обёрнута в try/except: недоступность админа (например, не открыт диалог с ботом) не валит поллер.

Уведомления об инцидентах уходят в топик `MESSAGE_THREAD_ID` (если задан) — `_send` принимает
`thread_id`, `_edit` его не требует (`message_id` уже адресует сообщение в его топике). Стартовый
пинг админу и команда `/test` в группе шлют в **личку без thread_id** — у лички топиков нет.

## Config (.env)

`load_config` (`config.py`) валидирует окружение и кидает `ConfigError` (→ `SystemExit(1)`):
`BOT_TOKEN` обязателен; `CHAT_ID` опционален (без него — только команды); `MESSAGE_THREAD_ID`
опционален (id топика форум-группы, куда слать уведомления; без него — в General); `ADMIN_ID`
опционален (получатель стартового пинга; без него пинг не шлётся); `POLL_INTERVAL` секунды
(default 120); `DISPLAY_TIMEZONE` проверяется через `zoneinfo` (default UTC). Есть также `AGENTS.md` с
гайдлайнами по стилю/коммитам/PR.

## Testing notes

Тесты в `tests/test_differ.py` офлайн проверяют RSS parsing, first-run seed, send/edit/resolved
actions, JSON enrichment и poller calls. При изменении RSS state shape или Telegram behavior
обновляйте эти тесты в первую очередь.
