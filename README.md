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
- **Реферальная программа** — пользователь получает бонусные дни за каждую оплату приглашённого друга
- Административное меню: управление пользователями, рассылка, статистика
- Автоматическая проверка и синхронизация подписок между 3x-ui и БД
- **Автоматическая миграция БД** при обновлении — не требует ручных действий

## Концепция тарифов и инбаундов

Каждый тариф — это набор инбаундов, заданных в `config.yaml`. Один пользователь получает профиль в **каждом** инбаунде своего тарифа. Все профили объединяются в одну подписку по `sub_id`: пользователь сканирует **один QR-код** и получает все серверы сразу.

```
Basic:   STANDARD_INBOUNDS: "1"        → один инбаунд
Premium: PREMIUM_INBOUNDS: "3"         → добавляет второй поверх базового
```

Протокол каждого инбаунда определяется автоматически из панели 3x-ui. Добавить серверы — только правка `config.yaml` и перезапуск бота.

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

3. Настройте конфигурацию:

```bash
cp src/config.example.yaml src/config.yaml  # отредактируйте под свои значения
```

4. Запустите бота:

```bash
source .venv/bin/activate
python3 src/app.py
```

### Настройка конфигурации (`config.yaml`)

#### Обязательные параметры

| Ключ | Описание |
|---|---|
| `BOT_TOKEN` | Токен Telegram-бота от @BotFather |
| `ADMINS` | Список ID администраторов, например `[123456789]` |
| `XUI_API_URL` | URL панели 3X-UI (например: `http://ip:54321`) |
| `XUI_API_TOKEN` | Bearer API-токен 3X-UI (Settings → API Keys → Generate API Key) |

#### Параметры панели

| Ключ | По умолчанию | Описание |
|---|---|---|
| `XUI_BASE_PATH` | `/panel` | Базовый путь к API панели |
| `XUI_SUB_PORT` | `54321` | Порт эндпоинта подписок (`/sub/`) |
| `XUI_VERIFY_SSL` | `false` | Проверять SSL-сертификат панели |
| `SUBSCRIPTION_URL_BASE` | — | Хост для ссылок подписки. Если не задан — берётся из `XUI_API_URL` |

#### Оплата (хотя бы один способ)

| Ключ | Описание |
|---|---|
| `PAYMENT_TOKEN` | Платёжный токен от @BotFather (не нужен при использовании только Tribute) |

#### Конфигурация тарифов

ID инбаундов из панели 3x-ui. Протокол определяется автоматически из панели.

| Ключ | По умолчанию | Описание |
|---|---|---|
| `STANDARD_INBOUNDS` | — | ID инбаундов базового тарифа через запятую |
| `PREMIUM_INBOUNDS` | — | ID инбаундов премиум-тарифа (добавляются поверх базовых). Оставьте пустым, если premium не нужен |
| `PREMIUM_PRICE_MULTIPLIER` | `1.5` | Цена Premium = цена Basic × коэффициент |
| `PREMIUM_TRAFFIC_LIMIT_GB` | `0` | Лимит трафика для premium-клиента в ГБ (`0` = безлимит) |
| `TRIAL_DAYS` | `3` | Длительность бесплатного пробного периода в днях |
| `TRIAL_TIER` | `standard` | Тариф пробного периода (`standard` или `premium`) |


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
│   ├── config.example.yaml       # Пример конфигурации
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

3. Пропишите ключи в `config.yaml`:

   | Ключ | Описание |
   |---|---|
   | `TRIBUTE_API_KEY` | API-ключ из Tribute Dashboard |
   | `TRIBUTE_WEBHOOK_PORT` | Порт webhook-сервера (по умолчанию `8081`) |
   | `TRIBUTE_SUBSCRIPTIONS` | Список подписок `{name, tier, url, referral_reward_days}` — имена должны точно совпадать с планами в Tribute Dashboard |
   | `TRIBUTE_DIGITAL_PRODUCTS` | Список цифровых товаров `{name, tier, hours, url, referral_reward_days}` |

4. В разделе **API Keys** укажите URL вебхука:
   ```
   https://your-domain.com:8081/tribute/webhook
   ```

5. Убедитесь, что порт `8081` открыт в файрволе (или используйте nginx-прокси).

#### Как работает

- При `newSubscription` / `renewedSubscription` — подписка активируется/продлевается, профили в 3x-ui создаются или обновляются автоматически.
- При `cancelledSubscription` — пользователь сохраняет доступ до конца оплаченного периода; профили удаляются стандартным hourly-чеком.
- Если пользователь оплатил через Tribute до того как нажал `/start` — запись в БД создаётся автоматически.

## Реферальная программа

Каждый пользователь получает уникальную реферальную ссылку вида `https://t.me/<bot>?start=<code>`. Когда новый пользователь регистрируется по этой ссылке и впоследствии оплачивает подписку через Tribute, реферер автоматически получает бонусные дни к своей подписке.

**Как настроить награду:**

Добавьте поле `referral_reward_days` к каждому плану Tribute, за который хотите начислять бонус. Рекомендуемое значение — **5 дней за каждый купленный месяц** (т.е. для плана на 1 месяц — 5, на 3 месяца — 15 и т.д.):

```yaml
TRIBUTE_SUBSCRIPTIONS:
  - name: "Standard 1 Month"
    tier: "standard"
    url: "https://tribute.tg/..."
    referral_reward_days: 5    # 1 месяц → 5 дней рефереру
  - name: "Standard 3 Months"
    tier: "standard"
    url: "https://tribute.tg/..."
    referral_reward_days: 15   # 3 месяца → 15 дней рефереру
  - name: "Premium 1 Month"
    tier: "premium"
    url: "https://tribute.tg/..."
    referral_reward_days: 5    # 1 месяц premium → 5 дней рефереру на premium

TRIBUTE_DIGITAL_PRODUCTS:
  - name: "VPN 1 Month"
    tier: "standard"
    hours: 720
    url: "https://tribute.tg/..."
    referral_reward_days: 5
```

- `referral_reward_days: 0` (по умолчанию) — вознаграждение не начисляется.
- Начисление происходит при каждой успешной оплате реферала (включая продления).
- **Тариф бонуса соответствует тарифу оплаченного плана**: купил реферал `standard` — реферер получает дни на `standard`, купил `premium` — на `premium`.
- Пользователь видит свою ссылку и статистику через кнопку **«👥 Рефералы»** в главном меню.

> Реферальная программа работает **только с Tribute**. Оплаты через Telegram Payments не учитываются.

## Мониторинг

Бот проверяет подписки каждый час:
- За 24 часа до окончания — уведомление пользователю
- При истечении — удаление клиентов из всех инбаундов, уведомление пользователю

## Возможные проблемы и решения

| Проблема | Решение |
|---|---|
| Ошибки подключения к 3X-UI | Проверьте `XUI_API_URL` и `XUI_API_TOKEN` |
| Профиль не создаётся | Убедитесь, что инбаунд с указанным ID существует в панели |
| Ссылки не приходят через `/connect` | Проверьте `XUI_SUB_PORT` и доступность эндпоинта `/sub/` |
| Проблемы с платежами | Проверьте `PAYMENT_TOKEN` |
| Tribute webhook не срабатывает | Проверьте `TRIBUTE_API_KEY` и доступность порта `TRIBUTE_WEBHOOK_PORT` извне |
| Tribute: 401 Unauthorized | API-ключ в `config.yaml` не совпадает с ключом в Tribute Dashboard |
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
