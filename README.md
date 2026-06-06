**Язык / Language:** <ins>Русский</ins> **|** [English](./docs/README.en_US.md)


<div id="header" align="center"><h1>XRay VPN bot [Telegram]</h1></div>

<div id="header" align="center"><img alt="GitHub last commit" src="https://img.shields.io/github/last-commit/QueenDekim/XRay-bot"> <img alt="GitHub commit activity" src="https://img.shields.io/github/commit-activity/m/QueenDekim/XRay-bot"><br><img alt="GitHub top language" src="https://img.shields.io/github/languages/top/QueenDekim/XRay-bot"> <a href="./LICENSE" target="_blank"><img alt="GitHub License" src="https://img.shields.io/github/license/QueenDekim/XRay-bot"></a></div>

## Описание проекта

Telegram бот для продажи и управления VPN-подписками через панель управления 3X-UI. Поддерживает протоколы **VLESS Reality** и **VLESS xhttp (XHTTP/SplitHTTP)**, два тарифных плана и неограниченное количество инбаундов на каждый тариф.

Основные возможности:

- Регистрация пользователей с бесплатным пробным периодом (3 дня)
- **Два тарифа: 📦 Basic и ⭐ Premium** — набор инбаундов для каждого задаётся в конфиге
- **Поддержка протоколов Reality и xhttp** — любое сочетание в рамках одного тарифа
- **Один QR-код на подписку** — 3x-ui агрегирует все конфиги по `sub_id`
- Продление подписки через встроенную платёжную систему Telegram
- Автоматическое создание и удаление профилей во всех инбаундах тарифа
- Уведомления об истечении подписки за 24 часа
- Генерация QR-кодов для быстрого подключения
- **Временные профили на 30 минут** для тестирования (веб-сервер)
- Административное меню: управление пользователями, рассылка, статистика
- Автоматическая проверка и синхронизация подписок между 3x-ui и БД
- **Автоматическая миграция БД** при обновлении — не требует ручных действий

## Концепция тарифов и инбаундов

Каждый тариф — это набор инбаундов, заданных в `.env`. Один пользователь получает профиль в **каждом** инбаунде своего тарифа. Все профили объединяются в одну подписку по `sub_id`: пользователь сканирует **один QR-код** и получает все серверы сразу.

```
Basic:   1:reality              → один Reality-сервер
Premium: 1:reality,3:xhttp     → Reality + xhttp одновременно
```

Добавить серверы или сменить протокол — только правка `.env` и перезапуск бота. Код менять не нужно.

## Установка и настройка

### Предварительные требования

- Python 3.10+
- Панель управления 3X-UI
  - Созданы инбаунды нужных типов (Reality, xhttp)
  - ID каждого инбаунда из URL панели при редактировании
- Telegram бот (созданный через `@BotFather`)
- SSL сертификаты для HTTPS (опционально, для веб-сервера тест-профилей)

### Шаги установки

1. Клонируйте репозиторий:

```bash
git clone https://github.com/QueenDekim/XRay-bot
cd XRay-bot
```

2. Установите зависимости (рекомендуется [uv](https://github.com/astral-sh/uv)):

```bash
uv venv && uv pip install -r requirements.txt
# или стандартно:
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

3. Настройте переменные окружения:

```bash
cp src/.env.example src/.env  # отредактируйте под свои значения
```

4. Запустите бота:

```bash
source .venv/bin/activate
python3 src/app.py
```

### Настройка переменных окружения

#### Обязательные параметры

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота от @BotFather |
| `ADMINS` | ID администраторов через запятую |
| `XUI_API_URL` | URL панели 3X-UI (например: `http://ip:54321`) |
| `XUI_HOST` | IP или домен сервера |
| `XUI_API_TOKEN` | Bearer API-токен 3X-UI (Settings → API Keys) |

#### Оплата (хотя бы один способ)

| Переменная | Описание |
|---|---|
| `PAYMENT_TOKEN` | Платёжный токен от @BotFather (не нужен при использовании только Tribute) |

#### Конфигурация тарифов

Формат: `"id:protocol,id:protocol"`, где `protocol` — `reality` или `xhttp`.

```bash
# Базовый тариф — только Reality
BASIC_INBOUNDS=1:reality

# Базовый с двумя серверами
BASIC_INBOUNDS=1:reality,2:reality

# Премиум — Reality + xhttp
PREMIUM_INBOUNDS=1:reality,3:xhttp

# Цена Premium = цена Basic × коэффициент (1.5 = +50%)
PREMIUM_PRICE_MULTIPLIER=1.5
```

#### Параметры каждого инбаунда

Задаются по схеме `INBOUND_{ID}_*`:

```bash
# Reality инбаунд (id=1)
INBOUND_1_PUBLIC_KEY=...
INBOUND_1_FINGERPRINT=chrome
INBOUND_1_SNI=example.com
INBOUND_1_SHORT_ID=...
INBOUND_1_SPIDER_X=/

# xhttp инбаунд (id=3)
INBOUND_3_SNI=example.com
INBOUND_3_PATH=/
INBOUND_3_SECURITY=tls
INBOUND_3_HOST=        # пусто = XUI_HOST
```

## Команды бота

### Пользовательские команды

| Команда | Описание |
|---|---|
| `/start` | Запуск бота и регистрация |
| `/menu` | Главное меню со статусом подписки и тарифом |
| `/renew` | Выбор тарифа и периода подписки |
| `/connect` | Получить QR-код и ссылку для подключения |
| `/stats` | Статистика использования трафика |
| `/help` | Справка |

### Административные функции

Доступны через кнопку «Админ. меню»:

- Добавление / удаление времени подписки (обновляет все инбаунды пользователя)
- Удаление пользователя с очисткой всех профилей в 3x-ui
- Список пользователей с фильтрацией по статусу подписки и тарифу
- **Проверка подписок** — выявляет расхождения между 3x-ui и БД по всем инбаундам
- **Исправить профили** — принудительно синхронизирует expiry во всех инбаундах
- Статистика использования сети
- Рассылка сообщений пользователям
- Управление статическими профилями

## Техническая архитектура

### Файловая структура

```
./
├── src/
│   ├── .env.example              # Пример конфигурации
│   ├── app.py                    # Точка входа, фоновые задачи
│   ├── config.py                 # Конфигурация (Pydantic), get_inbound_configs()
│   ├── database.py               # ORM-модели, migrate_database()
│   ├── functions.py              # XUIAPI, create_profile(), генерация URL
│   ├── handlers.py               # Обработчики команд и callback'ов
│   └── tribute_webhook.py        # FastAPI webhook-обработчик Tribute
├── docs/
│   └── README.en_US.md
├── README.md
└── requirements.txt
```

### База данных

SQLite + SQLAlchemy ORM. Миграция запускается автоматически при старте бота (`migrate_database()`).

**Таблица `users`:**

| Поле | Описание |
|---|---|
| `telegram_id` | ID пользователя в Telegram |
| `subscription_end` | Дата окончания подписки |
| `subscription_tier` | Тариф: `basic` или `premium` |
| `profiles_data` | JSON: `{"inbound_id": {...профиль...}, ...}` |
| `vless_profile_data` | Устаревшее поле (legacy, мигрируется автоматически) |
| `is_admin` | Флаг администратора |

**Таблица `static_profiles`:** статические профили без привязки к пользователям.

### Как работает подписка

1. Пользователь оплачивает тариф → бот создаёт клиента в **каждом** инбаунде тарифа
2. Каждый клиент получает одинаковый `sub_id` (UUID5 от telegram_id)
3. `GET /sub/{sub_id}` на 3x-ui возвращает **все** VLESS-конфиги пользователя
4. QR-код кодирует subscription URL — один для всех протоколов
5. При продлении expiry обновляется во всех инбаундах одновременно
6. При истечении подписки профили удаляются из всех инбаундов

### Форматы VLESS URL

**Reality:**
```
vless://{uuid}@{host}:{port}?type=tcp&security=reality&pbk={pbk}&fp={fp}&sni={sni}&sid={sid}&spx={spx}#{remark}
```

**xhttp:**
```
vless://{uuid}@{host}:{port}?type=xhttp&security=tls&path={path}&host={host}&sni={sni}#{remark}
```

## Работа с платежами

### Telegram Payments (встроено)

1. Пользователь выбирает тариф (Basic / Premium) и период
2. Бот создаёт Telegram-инвойс с ценой `calculate_price(months, tier)`
3. После успешной оплаты:
   - Обновляется `subscription_end` и `subscription_tier`
   - Создаются недостающие профили / обновляется expiry в существующих
   - При смене тарифа — лишние профили удаляются из 3x-ui

### Tribute (опционально)

[Tribute](https://tribute.tg) — платформа монетизации для Telegram. Преимущества перед Telegram Payments: иностранные карты, оплата криптовалютой (USDT/TON/BTC), автоматическое продление подписки.

Оба способа оплаты работают **одновременно**.

#### Настройка

1. Зарегистрируйтесь на [tribute.tg](https://tribute.tg) и создайте планы подписки.  
   Названия планов должны точно совпадать с `TRIBUTE_BASIC_PLAN_NAME` и `TRIBUTE_PREMIUM_PLAN_NAME`.

2. Получите API-ключ: Tribute Dashboard → **⋮ → Settings → API Keys → Generate API Key**

3. Пропишите переменные окружения:

   | Переменная | Описание |
   |---|---|
   | `TRIBUTE_API_KEY` | API-ключ из Tribute Dashboard |
   | `TRIBUTE_WEBHOOK_PORT` | Порт webhook-сервера (по умолчанию `8081`) |
   | `TRIBUTE_BASIC_PLAN_NAME` | Точное название базового плана в Tribute (по умолчанию `Basic`) |
   | `TRIBUTE_PREMIUM_PLAN_NAME` | Точное название премиум-плана в Tribute (по умолчанию `Premium`) |
   | `TRIBUTE_BASIC_URL` | Ссылка на страницу оплаты Basic-плана (Tribute Dashboard → «Поделиться»). Если не задана — кнопка «Оплатить через Tribute» в `/renew` не появляется |
   | `TRIBUTE_PREMIUM_URL` | Аналогично для Premium-плана |

4. В разделе **API Keys** укажите URL вебхука:
   ```
   https://your-domain.com:8081/tribute/webhook
   ```

5. Убедитесь, что порт `8081` открыт в файрволе (или используйте nginx-прокси).

#### Как работает

- При `newSubscription` / `renewedSubscription` — подписка активируется/продлевается, профили в 3x-ui создаются или обновляются автоматически.
- При `cancelledSubscription` — пользователь сохраняет доступ до конца оплаченного периода; профили удаляются стандартным hourly-чеком.
- Если пользователь оплатил через Tribute до того как нажал `/start` — запись в БД создаётся автоматически.

## Мониторинг

Бот проверяет подписки каждый час:
- За 24 часа до окончания — уведомление пользователю
- При истечении — удаление клиентов из всех инбаундов, уведомление пользователю

## Возможные проблемы и решения

| Проблема | Решение |
|---|---|
| Ошибки подключения к 3X-UI | Проверьте `XUI_API_URL`, логин и пароль |
| Профиль не создаётся | Убедитесь, что инбаунд с указанным ID существует в панели |
| xhttp-профиль отклоняется панелью | Проверьте, что `INBOUND_{ID}_SECURITY=tls` задан корректно |
| Проблемы с платежами | Проверьте `PAYMENT_TOKEN` |
| Tribute webhook не срабатывает | Проверьте `TRIBUTE_API_KEY` и доступность порта `TRIBUTE_WEBHOOK_PORT` извне |
| Tribute: 401 Unauthorized | API-ключ в `.env` не совпадает с ключом в Tribute Dashboard |
| Расхождения expiry | Используйте «Проверить подписки» в админ-меню |
| Некорректные даты | Используйте «Исправить профили» в админ-меню |
| Ошибки базы данных | Проверьте права на запись в директорию с `users.db` |

---

*Документация: [aiogram](https://docs.aiogram.dev/en/latest/) · [3X-UI](https://github.com/MHSanaei/3x-ui/wiki)*

---

## Donation USDT (TON Network):

| QR Code                      | Address                                            |
| ---------------------------- | -------------------------------------------------- |
| ![QR-code](docs/qr-code.jpg) | `UQA9SigQDdUlZhFj3C5L71gFwjs2kSZu1b9g7Huu1PQujrVS` |

| Demo - Полностью функциональный бот                    | Связь с разработчиком                            |
| ------------------------------------------------------ | ------------------------------------------------ |
| Telegram: [@Dekim_vpn_bot](https://t.me/Dekim_vpn_bot) | Telegram: [@QueenDek1m](https://t.me/QueenDek1m) |
|                                                        | Discord: `from_russia_with_love`                 |
