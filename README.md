# Claude Status Bot

Telegram-бот на **aiogram 3.x**, который следит за [status.claude.com](https://status.claude.com)
и присылает в чат уведомления об **инцидентах**.

Источник событий — RSS history feed. JSON API Statuspage используется только для обогащения
уведомлений: impact/status/иконка/shortlink и текущая сводка для `/test`.

## Возможности

- Уведомления о новых инцидентах и обновлениях по ним (включая `resolved`).
- Промежуточные обновления (`Investigating` → `Monitoring`) редактируют исходное сообщение.
- `Resolved` отправляется отдельным новым сообщением с зелёной галкой.
- Анти-спам: при первом запуске текущее состояние засевается молча, без рассылки истории.
- Команды: `/start`, `/test` (текущее состояние по запросу).

## Структура

```
app/
  config.py         # конфигурация из .env
  status_client.py  # RSS + JSON-запросы к Statuspage
  state.py          # атомарное чтение/запись состояния (data/state.json)
  differ.py         # чистая логика: RSS items + state -> send/edit actions
  formatter.py      # HTML-сообщения для Telegram
  poller.py         # фоновый цикл опроса и рассылки
  handlers.py       # команды бота
main.py             # точка входа (Bot + Dispatcher + поллер)
tests/              # офлайн-тесты диффа и форматтера
```

## Быстрый старт (локально)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# впишите BOT_TOKEN (от @BotFather)

python main.py
```

Чтобы узнать `CHAT_ID`, используйте Telegram-клиент или временно посмотрите входящее обновление
через Bot API. Проверить связь со Statuspage можно командой `/test`.

## Запуск в Docker

```bash
cp .env.example .env            # заполните BOT_TOKEN и CHAT_ID
docker build -t cc-status-bot .
docker run -d --restart unless-stopped \
  --env-file .env -v "$(pwd)/data:/app/data" \
  --name cc_status_bot cc-status-bot
docker logs -f cc_status_bot
```

Состояние сохраняется в `./data/state.json` (том примонтирован в контейнер).

## Конфигурация (.env)

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `BOT_TOKEN` | — (обязательно) | токен от @BotFather |
| `CHAT_ID` | — | чат для уведомлений; без него работают только команды |
| `POLL_INTERVAL` | `120` | интервал опроса, секунды |
| `DISPLAY_TIMEZONE` | `UTC` | таймзона для времени в сообщениях |

## Тесты

```bash
pytest -v
```

Тесты проверяют RSS-парсинг, анти-спам первого запуска, `send`/`edit`/`send_resolved` действия,
JSON enrichment и HTML-форматирование — без обращения к Telegram и сети.

### Проверить уведомление без реального инцидента

Отредактируйте `data/state.json`: замените сохранённый `pub_date` нужного `rss_items[guid]`
на старое значение и дождитесь следующего опроса. Non-resolved update будет редактировать
сохранённый `message_id`; resolved отправит новое зелёное сообщение.
