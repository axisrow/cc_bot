# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Telegram-бот на **aiogram 3.x**, который опрашивает публичный JSON API Atlassian Statuspage
(`status.claude.com/api/v2`) и шлёт в чат уведомления о новых инцидентах, плановых работах и
сменах статусов компонентов. HTML страницы не парсится — только JSON-эндпоинты.

## Commands

```bash
# Окружение
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # впишите BOT_TOKEN (обязательно), при желании CHAT_ID

# Запуск
python main.py

# Тесты (офлайн, без Telegram и сети)
pytest -v
pytest tests/test_differ.py::test_new_incident_emits_event   # один тест

# Docker (compose не используется)
docker build -t cc-status-bot .
docker run -d --restart unless-stopped --env-file .env -v "$(pwd)/data:/app/data" \
  --name cc_status_bot cc-status-bot
```

Нет линтера/форматтера в конфиге — стиль поддерживается вручную (`from __future__ import annotations`,
типизация, докстринги на русском).

## Architecture

`main.py` поднимает **два конкурентных asyncio-цикла** на одной общей `aiohttp.ClientSession`:
1. `dp.start_polling` — long-polling Telegram для команд (`app/handlers.py`).
2. `run_poller` — фоновая задача, опрашивающая статус-страницу (`app/poller.py`).

`config` и `status_client` прокидываются в хендлеры как контекстные kwargs через `start_polling`.

### Конвейер опроса (ядро)

`StatusClient.fetch()` → `diff()` → `format_event()` → `bot.send_message()` → `save_state()`.

- **`status_client.py`** — тянет три эндпоинта параллельно (`asyncio.gather`): `summary.json`
  (компоненты + общий индикатор), `incidents.json`, `scheduled-maintenances.json`. Инциденты и
  работы берутся из выделенных эндпоинтов (не из summary), чтобы видеть `resolved`/`completed`.
  Возвращает `StatusSnapshot`. База API захардкожена в константе `API_BASE`.
- **`differ.py`** — **чистая логика без сети и Telegram** (поэтому покрыта офлайн-тестами).
  Сравнивает `StatusSnapshot` с сохранённым состоянием и возвращает `(events, new_state)`.
- **`formatter.py`** — превращает `Event`/`StatusSnapshot` в HTML-сообщения (эмодзи по
  impact/статусу, экранирование, конвертация времени в `DISPLAY_TIMEZONE`).
- **`state.py`** — атомарная запись состояния (`tempfile` → `os.replace`) в `data/state.json`
  (путь захардкожен в константе `STATE_FILE`).

### Как детектируется изменение (важно)

Состояние — это «что уже отправили»: для инцидентов/работ хранится **id последнего обновления**
(`incident_updates[0].id`, API отдаёт новейшее первым), для компонентов — строка статуса.
`diff()` шлёт событие, если объект новый (`id` не в state) или у него изменился id обновления /
статус.

**Анти-спам при первом запуске:** если в состоянии нет ключа `initialized`, `diff()` молча
засевает текущие id/статусы и НЕ генерирует события — иначе бот спамил бы всей историей. Это
ключевая инвариант: при изменении логики диффа не сломайте «тихий» первый запуск.

Компоненты-группы (`group: true`) пропускаются — следим только за листовыми сервисами.

### Команды /start и /test

`app/handlers.py`: **`/start`** — приветствие с описанием бота; **`/test`** — бот отвечает текущим
статусом (`format_overall`) тому, кто её прислал (ручная проверка работоспособности). В остальном бот
автономен и на произвольные сообщения НЕ реагирует (никакого catch-all). Polling Telegram оставлен
ради приёма этих команд.

### Конфигурация

`app/config.py` → `Config` (frozen dataclass) из 4 env-переменных: `BOT_TOKEN` (обязателен),
`CHAT_ID` (без него уведомления не шлются — работают только команды), `POLL_INTERVAL`,
`DISPLAY_TIMEZONE`. Прочие параметры (база API, путь состояния) захардкожены константами в
соответствующих модулях.

## Testing notes

Тесты в `tests/test_differ.py` работают против фикстуры `tests/fixtures/sample.json` —
конструируют `StatusSnapshot` напрямую и проверяют, что одно изменение даёт ровно одно событие,
повторный опрос — ноль, а форматтер экранирует HTML. Сеть и Telegram не задействованы. При
изменении формы `StatusSnapshot`/`Event` синхронизируйте фикстуру и тесты.
