**Язык / Language:** [Русский](../README.md) **|** <ins>English</ins>

<div id="header" align="center"><h1>XRay VPN Bot [Telegram]</h1></div>

<div id="header" align="center"><img alt="GitHub last commit" src="https://img.shields.io/github/last-commit/QueenDekim/XRay-bot"> <img alt="GitHub commit activity" src="https://img.shields.io/github/commit-activity/m/QueenDekim/XRay-bot"><br><img alt="GitHub top language" src="https://img.shields.io/github/languages/top/QueenDekim/XRay-bot"> <a href="./LICENSE" target="_blank"><img alt="GitHub License" src="https://img.shields.io/github/license/QueenDekim/XRay-bot"></a></div>

## Project Description

This project is a Telegram bot for selling and managing VPN subscriptions via the 3X-UI control panel. The bot allows users to purchase VPN subscriptions, create and manage their profiles, and enables administrators to manage users and track statistics.

Key Features:

- User registration with a trial period
- Subscription renewal via Telegram's built-in payment system
- Creation and deletion of VPN profiles (VLESS) in the 3X-UI panel
- **Temporary 30-minute profiles for testing**
- Subscription expiration notifications
- **QR code generation for quick connection**
- **New quick access commands: /renew, /connect, /stats, /help**
- **Referral program** — users earn bonus days for every payment made by an invited friend
- Administrative menu for user management and broadcast messages
- Traffic usage statistics
- **Automatic subscription date and profile fixing**
- **Subscription verification and synchronization between 3x-ui and database**

## Installation and Setup

### Prerequisites

- Python 3.10+
- 3X-UI control panel
   - An inbound created with the security setting set to `Reality`
   - **Optional: separate inbound for temporary profiles**
- A Telegram bot (created via `@BotFather`)
- **SSL certificates for HTTPS (for temporary profiles)**

### Installation Steps

1. Clone the repository:

```bash
git clone https://github.com/QueenDekim/XRay-bot
cd XRay-bot
```

2. Install dependencies:

```bash
python -m venv .venv # use python3 on Linux
.venv\Scripts\activate
# source .venv/bin/activate on Linux
pip install -r requirements.txt
```

3. Configure environment variables:

```bash
cp src\.env.example src\.env # use "/" instead of "\" on Linux
# Edit the .env file with your values
```

4. Run the bot:

```bash
python src\app.py # use python3 and "/" instead of "\" on Linux
```

### Environment Variables Configuration

#### Mandatory parameters

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `ADMINS` | Administrator IDs, comma-separated |
| `XUI_API_URL` | 3X-UI panel URL (e.g., `http://ip:54321`) |
| `XUI_API_TOKEN` | Bearer API token from 3X-UI (Settings → API Keys → Generate API Key) |

#### Panel parameters

| Variable | Default | Description |
|---|---|---|
| `XUI_BASE_PATH` | `/panel` | Base path for 3X-UI API endpoints |
| `XUI_SUB_PORT` | `54321` | Port for the subscription endpoint (`/sub/`) |
| `XUI_VERIFY_SSL` | `False` | Verify panel SSL certificate (`True`/`False`) |
| `SUBSCRIPTION_URL_BASE` | — | Hostname for subscription links. Auto-detected from `XUI_API_URL` if empty |

#### Payment (at least one required)

| Variable | Description |
|---|---|
| `PAYMENT_TOKEN` | Telegram payment token from @BotFather (not needed if using Tribute only) |

#### Tier configuration

Inbound IDs from the 3x-ui panel. Protocol is detected automatically.

| Variable | Default | Description |
|---|---|---|
| `BASIC_INBOUNDS` | — | Inbound IDs for the Basic tier, comma-separated |
| `PREMIUM_INBOUNDS` | — | Inbound IDs for the Premium tier (added on top of Basic). Leave empty if Premium is not needed |
| `PREMIUM_PRICE_MULTIPLIER` | `1.5` | Premium price = Basic price × multiplier |
| `PREMIUM_TRAFFIC_LIMIT_GB` | `0` | Traffic limit for premium clients in GB (`0` = unlimited) |
| `TRIAL_DAYS` | `3` | Free trial period duration in days |
| `TRIAL_TIER` | `basic` | Tier for the trial period (`basic` or `premium`) |

#### Tribute (optional — second payment method)

[Tribute](https://tribute.tg) supports foreign cards, USDT/TON/BTC, and auto-renewal. Both payment methods work simultaneously.

| Variable | Default | Description |
|---|---|---|
| `TRIBUTE_API_KEY` | — | API key from Tribute Dashboard (Settings → API Keys) |
| `TRIBUTE_WEBHOOK_PORT` | `8081` | Port for the Tribute webhook server |
| `TRIBUTE_SUBSCRIPTIONS` | `[]` | List of subscriptions `{name, tier, url, referral_reward_days}` — names must match exactly in Tribute Dashboard |
| `TRIBUTE_DIGITAL_PRODUCTS` | `[]` | List of digital products `{name, tier, hours, url, referral_reward_days}` |

Webhook URL to register in Tribute Dashboard:
```
https://your-domain.com:8081/tribute/webhook
```

## Bot Commands

### User Commands

- `/start` - Start the bot and register
- `/menu` - Main menu
- `/renew` - Renew subscription
- `/connect` - Connect to VPN with QR code
- `/stats` - View usage statistics
- `/help` - Help

### Administrative Functions

Administrators have access to a special menu with functions:

- Adding/removing subscription time
- **Deleting users with profile cleanup in 3x-ui**
- Viewing the user list
- **Checking and fixing subscription discrepancies**
- **Fixing all profiles with incorrect dates**
- Network usage statistics
- Broadcasting messages to users
- Managing static profiles

## Technical Architecture

### File Structure

```
./
├── src/
│   ├── .env.example              # Example configuration
│   ├── app.py                    # Entry point, background tasks
│   ├── config.py                 # Configuration (Pydantic), get_inbound_configs()
│   ├── database.py               # ORM models, migrate_database()
│   ├── functions.py              # XUIAPI, create_profile(), URL generation
│   ├── handlers.py               # Command and callback handlers
│   └── tribute_webhook.py        # FastAPI webhook handler for Tribute
├── docs/
│   └── README.en_US.md
├── README.md
└── requirements.txt
```

### Database

The project uses `SQLite` with `SQLAlchemy ORM`. Main tables:

1. **`users`** - User information:
   - `telegram_id` - User's Telegram ID
   - `subscription_end` - Subscription end date
   - `subscription_tier` - Tier: `basic` or `premium`
   - `profiles_data` - JSON: `{"inbound_id": {...profile...}, ...}`
   - `is_admin` - Administrator flag
2. **`static_profiles`** - Static VPN profiles without a user binding:
   - `name` - Profile name
   - `vless_url` - VLESS URL

### Core Components

#### 1. `app.py`

The main application file that:
- Initializes the database
- Starts the background task for subscription checks
- Handles payment pre-checkout and successful payment queries
- **Registers bot commands in Telegram menu**
- Starts the bot's polling

#### 2. `config.py`

Loads and validates configuration using `Pydantic`. Contains:
- 3X-UI panel connection settings
- Reality protocol parameters
- Subscription prices and discounts
- Functions for cost calculation

#### 3. `database.py`

Models and functions for database interaction:
- `User` model for storing users
- `StaticProfile` model for static profiles
- Functions for managing subscriptions and profiles
- **validate_and_fix_subscription_date function for fixing dates**
- **delete_user function for deleting users**
- **get_users_with_profiles and fix_all_subscription_dates functions**

#### 4. `functions.py`

The `XUIAPI` class for interacting with the **3X-UI** panel:
- Panel authentication
- Creating and deleting clients
- **Updating profile expiry times**
- Retrieving usage statistics
- Generating VLESS URLs
- **get_safe_expiry_timestamp function for safe timestamp retrieval**
- **check_and_fix_subscriptions function for subscription verification**
- **force_update_profile_expiry function for forced updates**

#### 5. `handlers.py`

Command and callback handlers:
- `/start`, `/menu`, `/renew`, `/connect`, `/stats`, `/help` commands
- Payment processing
- Administrative functions
- Profile management
- **Handlers for new admin functions**

## Payment Processing

The bot uses Telegram's built-in payment system. When a subscription is selected:

1. The user selects a subscription period
2. The bot creates an invoice via `bot.send_invoice()`
3. After successful payment, it is processed by `process_successful_payment()`
4. The user's subscription is extended
5. **Automatically updates expiry_time in 3x-ui**

## Administrative Functions

Administrators have access to a special menu with functions:

- Adding/removing subscription time
- **Deleting users with full profile cleanup in 3x-ui**
- Viewing the user list
- **Checking subscriptions - identifying discrepancies between 3x-ui and DB**
- **Fixing profiles - automatic fixing of all dates**
- Network usage statistics
- Broadcasting messages to users
- Managing static profiles

## Integration with **3X-UI**

The bot interacts with the **3X-UI** panel via its API:

1. Authentication via login/password
2. Retrieving inbound data
3. Adding clients to the inbound settings
4. Updating the inbound configuration
5. **Updating expiry_time for existing clients**

## VLESS URL Generation

VLESS URL format for Reality:

```
vless://{client_id}@{host}:{port}?type=tcp&security=reality&pbk={public_key}&fp={fingerprint}&sni={sni}&sid={short_id}&spx={spider_x}#{remark}
```

## Referral Program

Every user gets a unique referral link: `https://t.me/<bot>?start=<code>`. When a new user registers via this link and later pays for a subscription through Tribute, the referrer automatically receives bonus days added to their subscription.

**How to configure rewards:**

Add a `referral_reward_days` field to each Tribute plan you want to reward. The recommended value is **5 days per purchased month** (e.g. 1-month plan → 5 days, 3-month plan → 15 days, etc.):

```yaml
TRIBUTE_SUBSCRIPTIONS:
  - name: "Standard 1 Month"
    tier: "standard"
    url: "https://tribute.tg/..."
    referral_reward_days: 5    # 1 month → 5 bonus days for referrer
  - name: "Standard 3 Months"
    tier: "standard"
    url: "https://tribute.tg/..."
    referral_reward_days: 15   # 3 months → 15 bonus days for referrer
  - name: "Premium 1 Month"
    tier: "premium"
    url: "https://tribute.tg/..."
    referral_reward_days: 5    # 1 month premium → 5 premium days for referrer

TRIBUTE_DIGITAL_PRODUCTS:
  - name: "VPN 1 Month"
    tier: "standard"
    hours: 720
    url: "https://tribute.tg/..."
    referral_reward_days: 5
```

- `referral_reward_days: 0` (default) — no reward is granted.
- The reward is issued on every successful payment by the referral (including renewals).
- **The bonus tier matches the purchased plan's tier**: if the referral buys `standard`, the referrer gets days on `standard`; if they buy `premium`, the referrer gets days on `premium`.
- Users can view their referral link and stats via the **"👥 Referrals"** button in the main menu.

> The referral program works **with Tribute only**. Telegram Payments purchases are not counted.

## Monitoring and Notifications

The bot automatically checks subscriptions every hour and:

- Notifies users 24 hours before expiration
- Deletes profiles with expired subscriptions
- Sends payment notifications to administrators
- **Fixes incorrect subscription dates**

## QR Code Generation

The bot automatically generates QR codes for profiles:
- Uses the `qrcode` library
- Creates a QR code with the profile subscription
- Sends the image to the user

## Temporary Profiles

The temporary profile functionality allows:
- Creating 30-minute profiles for testing
- Using a separate inbound for temporary profiles
- Automatically deleting profiles upon expiration
- Providing access through a web interface

## Prices and Discounts

The bot supports a flexible pricing system:
- 1 month - 100 rub.
- 3 months - 300 rub. (10% discount)
- 6 months - 600 rub. (20% discount)
- 12 months - 1200 rub. (30% discount)

## Security

- All sensitive data is stored in environment variables
- Configuration validation is done via Pydantic
- Restricted access to administrative functions
- Secure storage of payment information through Telegram
- **Validation and fixing of subscription dates**
- **Verification of discrepancies between 3x-ui and database**

## Potential Issues and Solutions

1. **3X-UI Connection Errors** - Check the URL and credentials
2. **Payment Issues** - Ensure the payment token is correct
3. **Database Errors** - Check write permissions in the directory
4. **Notifications Not Working** - Check time and timezone settings
5. **Incorrect Subscription Dates** - Use the "Fix Profiles" function in the admin menu
6. **Date Discrepancies** - Use the "Check Subscriptions" function in the admin menu

---

*For additional information, refer to the [aiogram](https://docs.aiogram.dev/en/latest/) and [3X-UI](https://github.com/MHSanaei/3x-ui/wiki) documentation.*

---

## Donation USDT (TON Network):

| QR Code                      | Address                                            |
| ---------------------------- | -------------------------------------------------- |
| ![QR-code](./qr-code.jpg)    | `UQA9SigQDdUlZhFj3C5L71gFwjs2kSZu1b9g7Huu1PQujrVS` |

| Demo - Fully functional bot                            | Communication with the developer                 |
| ------------------------------------------------------ | ------------------------------------------------ |
| Telegram: [@Dekim_vpn_bot](https://t.me/Dekim_vpn_bot) | Telegram: [@QueenDek1m](https://t.me/QueenDek1m) |
|                                                        | Discord: `from_russia_with_love`                 |
