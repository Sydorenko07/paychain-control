# Paychain Telegram Mini App

Темний Telegram Mini App керує **локальним** агентом користувача. Paychain-пароль, cookie та браузерний профіль залишаються на його комп’ютері.

## Компоненти

- `server.py` — центральний HTTPS-сервер, Mini App і WebSocket-команди.
- `bot.py` — Telegram-бот, який відкриває Mini App командою `/start`.
- `agent.py` — локальна програма на комп’ютері кожного користувача.
- `webapp/` — темний інтерфейс Mini App.

## Встановлення

На сервері:

```cmd
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy telegram_app\settings.example.env telegram_app\settings.env
```

У `telegram_app/settings.env` вкажи:

- `TELEGRAM_BOT_TOKEN` — токен від @BotFather;
- `APP_URL` — публічна HTTPS-адреса сервера, наприклад `https://app.example.com`;

Не додавай `settings.env` у Git і нікому не надсилай токен бота.

Запусти два процеси:

```cmd
.venv\Scripts\uvicorn.exe telegram_app.server:app --host 0.0.0.0 --port 8000
.venv\Scripts\python.exe telegram_app\bot.py
```

Для Telegram URL має бути доступний з інтернету через HTTPS. Локальний `http://localhost:8000` годиться лише для розробки у браузері, але не як робочий Mini App.

## Підключення користувача

1. Користувач відкриває `/start` у боті й натискає **Відкрити додаток**.
2. У Mini App натискає **Підключити цей комп’ютер**.
3. Створює на своєму ПК `telegram_app/agent-config.json` за показаним шаблоном.
4. Один раз запускає локальний `main.py`, вручну входить у Paychain, а потім зупиняє його — сесія лишається в `.browser-profile`.
5. Запускає агента:

```cmd
.venv\Scripts\python.exe telegram_app\agent.py
```

Тепер кнопки Mini App запускають і зупиняють тільки його локальний Playwright-процес. Після успішного прийняття угоди агент надсилає серверу суму, а сервер відправляє користувачу Telegram-сповіщення.

Кнопка **«Запустити»** вмикає автоматичне підтвердження угод, сума яких не менша за вказаний поріг. Перед першим реальним запуском перевір поріг і сесію Paychain на тесті.

## Розгортання на Railway

Створи на [Railway](https://railway.app/) порожній проєкт і підключи GitHub-репозиторій з цією папкою. У ньому створи **два** сервіси з одного репозиторію:

1. **web** — Start Command:

   ```text
   uvicorn telegram_app.server:app --host 0.0.0.0 --port $PORT
   ```

2. **bot** — Start Command:

   ```text
   python telegram_app/bot.py
   ```

В обидва сервіси додай однакову змінну `TELEGRAM_BOT_TOKEN`. У сервіс `web` додай Volume, змонтуй його в `/data`, а в Variables додай `DATABASE_PATH=/data/control.sqlite3`. Після цього згенеруй Railway-домен для сервісу **web**, скопіюй його у `APP_URL` в обох сервісах і зроби Redeploy.

Потім у @BotFather відкрий створеного бота → **Bot Settings** → **Menu Button** або **Main Mini App** та вкажи цей самий Railway URL. Telegram підтримує запуск Mini App з кнопки меню та Main Mini App, що налаштовуються через BotFather. [Документація Telegram](https://core.telegram.org/bots/webapps)

## Вартість

Створення Telegram-бота та Mini App безкоштовні. Telegram прямо вказує, що Bot Platform безкоштовна для користувачів і розробників. Окремо може коштувати цілодобовий HTTPS-хостинг, домен або тунель до домашнього ПК. [Telegram Bots](https://core.telegram.org/bots)
