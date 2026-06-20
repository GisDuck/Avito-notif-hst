# Avito Telegram notifier

Простой приватный Telegram-бот, который опрашивает Avito API и присылает уведомления о новых непрочитанных входящих сообщениях.

## Что умеет

- Первый пользователь, который написал `/start` при пустом `data/users.txt`, становится главным админом.
- Админ получает одноразовый инвайт командой `/invite`.
- Новый пользователь без доступа должен отправить боту инвайт-код. После этого он записывается как сотрудник.
- Все пользователи из `data/users.txt` получают уведомления.
- Только админ видит `/users` и может удалить сотрудника кнопкой.
- Бот хранит данные в трех файлах:
  - `data/users.txt`
  - `data/invites.txt`
  - `data/processed_messages.txt`

## Настройка

1. Создайте Telegram-бота через BotFather и получите `TELEGRAM_BOT_TOKEN`.
2. Создайте приложение в кабинете Avito для API и получите `AVITO_CLIENT_ID` и `AVITO_CLIENT_SECRET`.
3. Скопируйте `.env.example` в `.env` и заполните значения.
4. Если бот не сможет сам получить id аккаунта Avito, укажите его в `AVITO_USER_ID`.

```env
TELEGRAM_BOT_TOKEN=123456:replace_me
AVITO_CLIENT_ID=replace_me
AVITO_CLIENT_SECRET=replace_me
AVITO_USER_ID=
POLL_INTERVAL_SECONDS=10
GROUP_WINDOW_SECONDS=10
AVITO_LOG_RESPONSES=false
AVITO_DEBUG_FETCH_ALL_CHATS=false
DATA_DIR=./data
```

## Запуск в Docker

```bash
docker compose up -d --build
```

Логи:

```bash
docker compose logs -f
```

Остановка:

```bash
docker compose down
```

## Локальный запуск

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m src.main
```

## Важное про Avito

Бот использует OAuth `client_credentials` и эндпоинты мессенджера Avito:

- получение списка чатов;
- получение сообщений чата;
- фильтрация только чатов с `unread_count > 0`.

Если у вашего Avito-приложения мессенджер требует другой тип OAuth-доступа, нужно будет заменить получение токена в `src/avito_api.py` на выданный Avito способ авторизации. Остальная логика бота от этого не меняется.

## Диагностика Avito

Если бот видит чаты, но не присылает сообщения, временно добавьте в `.env`:

```env
AVITO_LOG_RESPONSES=true
AVITO_DEBUG_FETCH_ALL_CHATS=true
```

После пересборки в логах появятся:

- JSON-ответы Avito API без `access_token`;
- ключи, которые реально пришли в объектах чатов;
- найденное поле непрочитанных сообщений;
- количество чатов, по которым бот сходил за сообщениями.

`AVITO_DEBUG_FETCH_ALL_CHATS=true` нужен только для проверки. В обычном режиме лучше вернуть `false`, чтобы бот не дергал сообщения по всем чатам без необходимости.
