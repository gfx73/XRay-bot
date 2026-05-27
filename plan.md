# Plan: Добавление xhttp-подписок и тарифов Basic/Premium

## Context

Проект XRay-bot продаёт VLESS+Reality VPN-подписки через Telegram. Задача — добавить протокол xhttp (XHTTP/SplitHTTP transport в Xray-core) и ввести два тарифа:
- **Basic** — набор инбаундов задаётся через конфиг (по умолчанию только Reality)
- **Premium** — расширенный набор (Reality + xhttp, или любой другой)

Архитектура позволяет добавлять любое количество инбаундов любого типа в любой тариф — только через env-переменные, без изменения кода.

---

## Ключевой принцип: один QR-код на пользователя

3x-ui subscription endpoint (`/sub/{sub_id}`) возвращает **все** VLESS-конфиги со всех инбаундов, у которых совпадает `sub_id`. Это штатная фича 3x-ui для агрегации нескольких подключений в одну подписку.

```
Инбаунд 1 (Reality):  client { uuid: "aaa", email: "user_123_abc", sub_id: "XYZ" }
Инбаунд 3 (xhttp):    client { uuid: "bbb", email: "user_123_def", sub_id: "XYZ" }
                                                                          ↑ одинаковый

GET /sub/XYZ  →  3x-ui возвращает оба VLESS-конфига одним ответом
```

VPN-приложение (v2rayNG, Hiddify и т.д.) при импорте subscription URL получает все серверы сразу. **Пользователю показывается один QR-код** — независимо от числа инбаундов в тарифе. Логика `/connect` не усложняется.

`sub_id` = `uuid5(telegram_id)` — детерминированный, одинаковый для всех инбаундов одного пользователя. Это уже так в текущем коде.

`profiles_data` (JSON dict `{inbound_id: profile_data}`) нужен только боту — для управления: удаление, обновление expiry по каждому инбаунду отдельно.

---

## Архитектура: Гибкая конфигурация инбаундов

### Конфигурация тарифов (`.env`)

Тариф задаётся списком пар `id:protocol`:

```bash
# Стандартная подписка — один Reality
BASIC_INBOUNDS=1:reality

# Несколько серверов в базовом тарифе
BASIC_INBOUNDS=1:reality,2:reality

# xhttp в базовом тарифе (будущее)
BASIC_INBOUNDS=1:reality,3:xhttp

# Премиум
PREMIUM_INBOUNDS=1:reality,3:xhttp
```

### Параметры каждого инбаунда

Для каждого `id` — отдельный набор переменных по схеме `INBOUND_{ID}_*`:

```bash
# Reality-инбаунд id=1
INBOUND_1_PUBLIC_KEY=xxx
INBOUND_1_SNI=example.com
INBOUND_1_FINGERPRINT=chrome
INBOUND_1_SHORT_ID=xxx
INBOUND_1_SPIDER_X=/

# xhttp-инбаунд id=3
INBOUND_3_SNI=example.com
INBOUND_3_PATH=/api
INBOUND_3_SECURITY=tls
INBOUND_3_HOST=              # пусто → используется XUI_HOST

# Временные тест-инбаунды
TEMP_INBOUND_CONFIGS=2:reality,4:xhttp
INBOUND_2_PUBLIC_KEY=xxx
INBOUND_4_SNI=example.com
```

### Хранение профилей в БД

Один столбец `profiles_data` — JSON dict, ключ = inbound_id:

```json
{
  "1": { "client_id": "uuid-aaa", "email": "user_123_abc", "sub_id": "XYZ", "security": "reality", "port": 443, "pbk": "...", "fp": "chrome", "sni": "...", "sid": "...", "spx": "/", "inbound_id": 1 },
  "3": { "client_id": "uuid-bbb", "email": "user_123_def", "sub_id": "XYZ", "security": "tls",     "port": 443, "path": "/api", "sni": "...", "host": "...", "inbound_id": 3 }
}
```

Backwards-compatibility: при старте, если `profiles_data` пуст, но `vless_profile_data` заполнен — автоматически мигрировать в `profiles_data[str(INBOUND_ID)]`.

---

## Файлы для изменения

### 1. `src/config.py`

Добавить поля:

```python
BASIC_INBOUNDS: str = "1:reality"
PREMIUM_INBOUNDS: str = "1:reality,3:xhttp"
PREMIUM_PRICE_MULTIPLIER: float = 1.5
```

Добавить метод:

```python
def get_inbound_configs(self, tier: str) -> list[dict]:
    """
    Парсит BASIC_INBOUNDS / PREMIUM_INBOUNDS и подтягивает
    INBOUND_{ID}_* переменные для каждого инбаунда.
    Возвращает: [{"id": 1, "protocol": "reality", "public_key": "...", ...}, ...]
    """
    raw = self.PREMIUM_INBOUNDS if tier == "premium" else self.BASIC_INBOUNDS
    result = []
    for part in raw.split(","):
        inbound_id_str, protocol = part.strip().split(":")
        inbound_id = int(inbound_id_str)
        params = {"id": inbound_id, "protocol": protocol}
        prefix = f"INBOUND_{inbound_id}_"
        for key, val in os.environ.items():
            if key.startswith(prefix):
                params[key[len(prefix):].lower()] = val
        result.append(params)
    return result

def get_temp_inbound_configs(self) -> list[dict]:
    """Аналогично для TEMP_INBOUND_CONFIGS."""
    ...
```

Обновить `.env.example`.

Старые поля `INBOUND_ID`, `REALITY_PUBLIC_KEY` и т.д. — оставить для backwards-compat (используются при миграции).

---

### 2. `src/database.py`

**Новые столбцы модели `User`:**

```python
subscription_tier: Mapped[str] = mapped_column(String, default="basic", server_default="basic")
profiles_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
# Старые vless_profile_id, vless_profile_data — оставить, не удалять
```

**Функция `migrate_database()`** (запускается при старте `app.py`):

```python
async def migrate_database():
    # 1. Добавить новые столбцы (идемпотентно — ошибка = столбец уже есть)
    async with engine.begin() as conn:
        for stmt in [
            "ALTER TABLE users ADD COLUMN subscription_tier TEXT NOT NULL DEFAULT 'basic'",
            "ALTER TABLE users ADD COLUMN profiles_data TEXT",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass

    # 2. Мигрировать vless_profile_data → profiles_data для существующих пользователей
    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(User).where(User.vless_profile_data != None, User.profiles_data == None)
        )
        for user in result.scalars():
            old = json.loads(user.vless_profile_data)
            old["inbound_id"] = config.INBOUND_ID
            user.profiles_data = json.dumps({str(config.INBOUND_ID): old})
        await session.commit()
```

**Обновить `delete_user()`** — перебирать все ключи `profiles_data` и удалять клиента из каждого инбаунда.

---

### 3. `src/functions.py`

**a) Универсальная `XUIAPI.create_profile(telegram_id, expiry_time, inbound_cfg)`:**

Ветвится по `inbound_cfg["protocol"]`:

```python
async def create_profile(self, telegram_id: int, expiry_time: int, inbound_cfg: dict) -> Optional[dict]:
    protocol = inbound_cfg["protocol"]
    inbound_id = inbound_cfg["id"]
    inbound = await self.get_inbound(inbound_id)
    # ...
    if protocol == "reality":
        new_client = {
            "id": client_id, "email": email, "expiryTime": expiry_time,
            "subId": sub_id,
            "fingerprint": inbound_cfg.get("fingerprint", "chrome"),
            "publicKey": inbound_cfg["public_key"],
            "shortId": inbound_cfg["short_id"],
            "spiderX": inbound_cfg.get("spider_x", "/"),
            "flow": "xtls-rprx-vision",
        }
    elif protocol == "xhttp":
        new_client = {
            "id": client_id, "email": email, "expiryTime": expiry_time,
            "subId": sub_id,
            "flow": "",
            # НЕТ Reality-полей — иначе 3x-ui вернёт ошибку
        }
    # Добавить клиента в inbound, обновить через API
    # Вернуть profile_data с полем "inbound_id": inbound_id
```

Возвращаемый dict включает `"inbound_id": inbound_id` — для роутинга при последующих операциях.

Старые `create_vless_profile()` оставить как deprecated обёртку.

**b) Параметр `inbound_id` в методах XUIAPI:**

```python
XUIAPI.delete_client(email, inbound_id)
XUIAPI.update_client_expiry(email, expiry_time, inbound_id)
XUIAPI.get_all_clients(inbound_id)
force_update_profile_expiry(email, subscription_end, inbound_id)
```

Дефолт — `config.INBOUND_ID`. Существующие вызовы не ломаются.

**c) Хелпер:**

```python
def inbound_id_from_profile(profile_data: dict) -> int:
    return profile_data.get("inbound_id", config.INBOUND_ID)
```

**d) `generate_vless_url(profile_data)` — ветвление по `profile_data["security"]`:**

```python
def generate_vless_url(profile_data: dict) -> str:
    security = profile_data.get("security", "reality")
    if security == "reality":
        return f"vless://...?type=tcp&security=reality&pbk=...&fp=...&sni=...&sid=...&spx=...#..."
    else:  # xhttp
        return f"vless://...?type=xhttp&security={security}&path=...&host=...&sni=...#..."
```

**e) `check_and_fix_subscriptions()`** — собирает клиентов из всех уникальных инбаундов обоих тарифов:

```python
all_inbound_ids = set()
for tier in ("basic", "premium"):
    for cfg in config.get_inbound_configs(tier):
        all_inbound_ids.add(cfg["id"])

all_clients = []
for inbound_id in all_inbound_ids:
    clients = await api.get_all_clients(inbound_id) or []
    all_clients += [{**c, "_inbound_id": inbound_id} for c in clients]
```

**f) Модульный враппер:**

```python
async def create_profile(telegram_id, expiry_time, inbound_cfg) -> Optional[dict]:
    api = XUIAPI()
    try:
        return await api.create_profile(telegram_id, expiry_time, inbound_cfg)
    finally:
        await api.close()
```

---

### 4. `src/app.py`

```python
# При старте — запустить миграцию
await migrate_database()

# check_subscriptions() — при удалении истёкших профилей перебирать все инбаунды:
profiles = json.loads(user.profiles_data or "{}")
for inbound_id_str, profile in profiles.items():
    await delete_client_by_email(profile["email"], int(inbound_id_str))
user.profiles_data = None
```

---

### 5. `src/handlers.py`

**a) `/renew` — два раздела тарифов:**

```
📦 Basic                    ⭐ Premium
[1 мес — 200₽]             [1 мес — 300₽]
[3 мес — 500₽]             [3 мес — 750₽]
...                         ...
```

Callback-data: `"pay_basic_1"`, `"pay_premium_3"` и т.д.
Invoice payload кодирует тариф: `f"{tier}_{months}"` → `"basic_1"` / `"premium_3"`.

**b) `process_successful_payment()`:**

1. Декодировать `tier` и `months` из payload
2. `user.subscription_tier = tier`
3. `inbound_configs = config.get_inbound_configs(tier)`
4. Для каждого `cfg` в `inbound_configs`:
   - Если профиль для этого инбаунда уже есть → `update_client_expiry(email, expiry, cfg["id"])`
   - Если нет → `create_profile(telegram_id, expiry, cfg)`, сохранить в `profiles_data[str(cfg["id"])]`
5. Если пользователь понизил тариф (инбаундов стало меньше) — удалить лишние профили из 3x-ui

**c) `/connect` — один QR-код:**

Логика не усложняется. Берём `sub_id` из любого профиля в `profiles_data` (он одинаков у всех) и отдаём QR с `/sub/{sub_id}`. Сырые VLESS-ссылки можно показать списком под QR.

```python
profiles = json.loads(user.profiles_data or "{}")
if not profiles:
    # создать профили для текущего тарифа пользователя
    ...
# sub_id одинаковый у всех → берём из первого профиля
sub_id = next(iter(profiles.values()))["sub_id"]
sub_url = generate_sub_url(sub_id)
# QR-код из sub_url
```

**d) Admin-хэндлеры** (`add_time`, `remove_time`) — обновлять expiry во **всех** инбаундах из `profiles_data`:

```python
profiles = json.loads(user.profiles_data or "{}")
for inbound_id_str, profile in profiles.items():
    await update_client_expiry(profile["email"], new_expiry, int(inbound_id_str))
```

---

### 6. `src/temp_profile_server.py`

- `TEMP_INBOUND_CONFIGS=2:reality,4:xhttp` + `INBOUND_2_*`, `INBOUND_4_*`
- Главная `/` — кнопки выбора для каждого temp-инбаунда (если один — сразу профиль)
- Endpoint `/test/{inbound_id}` — создаёт temp-профиль нужного типа
- `TempProfileAPI.create_profile(inbound_cfg)` — универсальный метод (аналог основного)
- Temp-профили не используют `profiles_data` (хранятся в памяти), `sub_id` не нужен

---

## Последовательность реализации

1. **config.py** — `BASIC_INBOUNDS`, `PREMIUM_INBOUNDS`, `get_inbound_configs()`
2. **database.py** — новые столбцы, `migrate_database()` с конвертацией старых данных
3. **functions.py** — `create_profile()`, обновить сигнатуры, `generate_vless_url()`, `check_and_fix`
4. **app.py** — вызов `migrate_database()`, обновить `check_subscriptions()`
5. **handlers.py** — тарифы в `/renew`, payment flow, `/connect`, admin
6. **temp_profile_server.py** — универсальные тест-профили

---

## Оценка сложности

**Уровень: Средний-Высокий** (~18–22 часа)

| Модуль | Часы |
|---|---|
| config.py + `get_inbound_configs()` | 1.5 |
| database.py + миграция + конвертация | 2.0 |
| functions.py (`create_profile`, URL-gen, check/fix) | 4.0 |
| app.py | 0.5 |
| handlers.py (тарифы, connect, payments, admin) | 7.0 |
| temp_profile_server.py | 2.5 |
| Тестирование end-to-end | 2.5 |

**Основные риски:**
- `create_profile` для xhttp **не должен** передавать Reality-поля в 3x-ui (иначе панель вернёт ошибку)
- Payload Telegram-инвойса кодирует тариф (`"premium_3"`) — `process_successful_payment` должен его декодировать
- При даунгрейде тарифа (premium → basic) — обязательно удалить лишние профили из 3x-ui
- Миграция `vless_profile_data` → `profiles_data` должна пройти без потерь данных

---

## Проверка (Verification)

1. Купить Basic → `subscription_tier="basic"`, `profiles_data={"1": {...}}`, один QR в `/connect`
2. Купить Premium → `profiles_data={"1": {...}, "3": {...}}`, один QR (содержит оба конфига через sub_id)
3. Добавить `BASIC_INBOUNDS=1:reality,2:reality` → Basic-пользователь получает два профиля, один QR
4. Expiry-checker → удаляет клиентов из **всех** инбаундов пользователя
5. Admin «добавить 30 дней» → обновляет expiry во всех инбаундах
6. `check_and_fix_subscriptions` → находит клиентов во всех инбаундах обоих тарифов
7. Temp-профиль на вебсервере: выбор Reality/xhttp, автоудаление через 30 минут
8. Существующие пользователи после деплоя: `vless_profile_data` → `profiles_data` мигрирован корректно
