# pkr_stablecoin — MVP (Django)

Minimal, **happy-path** demo of a PKR-pegged stablecoin with a Django **orchestrator** that coordinates:

* **Bank/fiat** side (webhook + payout API)
* **Stacks** (stubbed Chain Adapter today; Clarity later)
* **Internal ledger & DB**

It enforces: **“no token without money, no money without token.”**

**Demo-only**: simplified security, no KYC/AML. Both “wallet” and “chain” are **DB-backed stubs** for deterministic behavior and easy inspection.

---

## What’s new in this version

* **Bank webhook** (`POST /api/webhooks/bank`) with **HMAC signature** and optional **IP allowlist** → verified **fiat credit** → **mint**.
* **Stacks chainhook** webhook (`POST /api/webhooks/stacks`) → verified **on-chain burn** → **fiat payout** (wallet debit).
* **Stronger idempotency** across webhooks & jobs (bank `provider_tx_id`, chain `txid+event_index`, and job **Idempotency-Key** header).
* **New models**: `OnchainEvent`, `PayoutJob`, `UserPayoutMethod`, `ReconciliationRun`, `ExternalTransaction.status`.
* **Safer unit conversions** via `Decimal` (`core/constants.py`): `pkr_to_units`, `units_to_pkr`.
* **One-shot reconciliation** view aligns chain stub with local balance.

---

## Architecture & Concepts

* **Django API**, **PostgreSQL (via Docker)** by default. (SQLite supported for local no-Docker dev.)
* **Stubs**:

  * `wallet_stub`: simulates a PKR wallet account + tx log (credits/debits).
  * `chain_stub`: simulates an ERC-20-like balance and receipts (“on-chain”).
* **Units**: `TOKEN_DECIMALS = 6` → `1 PKR == 1_000_000 token units`.
* **Core tables** (selected):

  * Provider side (stub): `wallet_stub_walletstubaccount`, `wallet_stub_walletstubtx`
  * **Ingested bank txs**: `core_externaltransaction` (now with `status`: `RECEIVED|MINTED|IGNORED`)
  * **On-chain events**: `core_onchainevent` (idempotency: `txid + event_index`)
  * **Fiat payouts**: `core_payoutjob`
  * **Chain jobs**: `core_chainjob` (each mint/burn, includes `idempotency_key`)
  * **Balances**: `core_tokenbalance` (cache), `chain_stub_chainstubbalance` (“on-chain”)
  * **Ledger**: `core_ledgerentry` (issuer vs user entries per mint/burn)
  * **Recon**: `core_reconciliationrun` (daily snapshots)

---

## Prereqs

* Docker & Docker Compose v2 (Compose auto-loads `.env` in repo root)

---

## Quick Start (Docker — recommended)

1. **Clone & env**

```bash
git clone https://github.com/<you>/pkr_stablecoin.git
cd pkr_stablecoin
cp .env.example .env
```

**Useful `.env` defaults (safe for local demo):**

```
DB_ENGINE=postgres
POSTGRES_DB=pkr_demo
POSTGRES_USER=pkr_demo
POSTGRES_PASSWORD=pkr_demo
POSTGRES_HOST=db
POSTGRES_PORT=5432

ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
DJANGO_SETTINGS_MODULE=pkr_stablecoin.settings
DEBUG=1
DJANGO_SECRET_KEY=dev-insecure-please-change

# Demo user
DEMO_USER_EMAIL=hassan@bitcoinl2labs.com

# Bank webhook security
BANK_WEBHOOK_SECRET=dev-secret-change-me
# optional CIDRs (empty = allow all for dev)
# BANK_WEBHOOK_IP_ALLOWLIST=203.0.113.0/24,198.51.100.10/32

# Optional ceilings
MAX_SINGLE_MINT_PKR=5000000.00
MAX_SINGLE_PAYOUT_PKR=5000000.00

# Token decimals (default 6)
TOKEN_DECIMALS=6
```

> ⚠️ If you previously exported any `POSTGRES_*` in your shell, **unset** them; shell env overrides `.env`.

2. **Start the stack**

```bash
docker compose up --build
```

This brings up Postgres 15 and the Django app (gunicorn), applies migrations, and exposes the API at `http://localhost:8000`.

3. **Health**

```bash
curl http://localhost:8000/api/health
# {"ok": true}
```

---

## CSRF (curl/Postman)

This project keeps Django’s CSRF **enabled**. For POSTs:

```bash
# Get cookie + CSRF token, save cookie jar
curl -s -c cookies.txt http://localhost:8000/api/csrf > /dev/null
TOKEN=$(awk '$6=="csrftoken"{print $7}' cookies.txt | tail -n1)
```

> Always use the **same origin** for token fetch and subsequent POSTs.

---

## End-to-End Flows (Happy Path)

### A) **Bank-first mint** (webhook → mint)

**1) Seed demo user + wallet**

```bash
curl -X POST http://localhost:8000/api/demo/seed \
  -b cookies.txt -H "X-CSRFToken: $TOKEN"
# {"user_id":"<uuid>","wallet_account":"WALLET-001"}
```

**2) Simulate a bank webhook (credit, HMAC-signed)**

```bash
DEMO_EMAIL=hassan@bitcoinl2labs.com
BODY='{"provider_tx_id":"bank-001","direction":"credit","amount_pkr":"20000.00","status":"settled","metadata":{"user_email":"'"$DEMO_EMAIL"'"}}'
SIG=$(printf %s "$BODY" | openssl dgst -sha256 -hmac "dev-secret-change-me" -hex | awk '{print $2}')

curl -X POST http://localhost:8000/api/webhooks/bank \
  -H "Content-Type: application/json" \
  -H "X-Signature: $SIG" \
  -d "$BODY"
# {"ok": true, "minted": true, "tx_hash": "..."}
```

**3) Check balance & reconciliation**

```bash
curl -s http://localhost:8000/api/balance
curl -s http://localhost:8000/api/debug/summary | jq .
```

You should see **minted units** reflect 20,000 PKR → `20,000,000,000` units, and `match: true`.

---

### B) **Chain-first payout** (on-chain burn event → bank payout)

We simulate **Stacks Chainhook** delivering a burn event payload. The webhook extracts events, records an `OnchainEvent`, and immediately creates a `PayoutJob` (wallet **debit**).

```bash
DEMO_EMAIL=hassan@bitcoinl2labs.com
curl -X POST http://localhost:8000/api/webhooks/stacks \
  -H "Content-Type: application/json" \
  -d '{"events":[{"type":"burn","txid":"0xdeadbeef","event_index":0,"user_address":"'"$DEMO_EMAIL"'","amount_units":3000000000,"asset":"SP...::pkr"}]}'
# {"ok": true, "events": 1}

# Inspect payout jobs inside container (optional)
docker compose exec web python manage.py shell --command \
"from core.models import PayoutJob; print(list(PayoutJob.objects.values('status','amount_pkr','payout_ref')))"
```

Expected: one `PayoutJob` with `status='SUCCESS'`, `amount_pkr='3000.00'`.

> **Event formats:** the webhook supports a simple `{"events":[...]}` shape or a Chainhook-ish `{"transactions":[... "events":[...]]}` shape. Adjust to your actual Clarity event indexer later.

---

### C) **Fiat-first redemption** (web2 app → bank payout → burn)

User clicks Withdraw in app. The orchestrator burns on chain **after** successful bank payout (custodial pattern). Demo endpoint shows burn + wallet debit with **idempotency**.

```bash
KEY=$(python - <<'PY'
import uuid;print(uuid.uuid4())
PY)

curl -X POST http://localhost:8000/api/redeem \
  -b cookies.txt -H "X-CSRFToken: $TOKEN" \
  -H "Idempotency-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount_units": 5000000000, "memo": "withdraw 5k"}'
# 201 Created with {"job_id","tx_hash":"0xBURN","amount_units":"5000000000"}

curl -s http://localhost:8000/api/balance
curl -s http://localhost:8000/api/debug/summary | jq .
```

Re-POST the **same** request with the **same** `Idempotency-Key` → returns the **same job**, **no state change**.

Try redeeming more than your balance → `400 {"error":"insufficient_balance"}`.

---

## Endpoint Cheat Sheet

**Operational**

* `GET  /api/health` → health check
* `GET  /api/csrf` → issue CSRF cookie/token
* `POST /api/demo/seed` → create/fetch demo user + wallet
* `POST /api/demo/wallet/credit` `{amount_pkr,memo}` → simulate wallet **deposit** (stub)
* `POST /api/ingest/wallet-transactions` `{since}` → pull provider txs, **mint** credits (optional legacy path)
* `POST /api/mint` `{provider_tx_id}` → manually mint a specific ingested credit (optional)
* `POST /api/redeem` `{amount_units,memo}` + `Idempotency-Key` → **burn** + wallet **debit**

**Webhooks**

* `POST /api/webhooks/bank` → **HMAC** verified bank events (credits mint; debits recorded, ignored for mint).

  * Headers: `X-Signature: <sha256-hmac-hex>` (body signed with `BANK_WEBHOOK_SECRET`)
  * Optional `occurred_at` ISO8601; otherwise server timestamps it.
* `POST /api/webhooks/stacks` → Chainhook / simple payload with **burn** events → **payout**.

**Reads**

* `GET  /api/balance` → token units + decimals (cache)
* `GET  /api/ledger` → recent issuer/user ledger entries
* `GET  /api/external-transactions` → ingested wallet txs
* `GET  /api/debug/summary` → single-shot reconciliation (mints/burns vs balances)

---

## Security & Correctness (demo settings)

* **Sign** bank webhooks with HMAC (`BANK_WEBHOOK_SECRET`), optional **IP allowlist** (`BANK_WEBHOOK_IP_ALLOWLIST`).
* **Idempotency keys**:

  * Bank webhook: **`provider_tx_id`** (and we pass `idempotency_key=f"bank:{provider_tx_id}"` to mint job)
  * On-chain events: **`txid + event_index`**
  * Mint/Burn jobs: **`Idempotency-Key`** HTTP header
* **Amount ceilings**: `MAX_SINGLE_MINT_PKR`, `MAX_SINGLE_PAYOUT_PKR` (optional; set in env).
* **Unit conversions**: `core/constants.py` uses `Decimal` and **rounds down** to avoid over-issuance.

---

## One-shot reconciliation

```bash
curl -s http://localhost:8000/api/debug/summary | jq .
```

Expect `net_units == token_balance_units == chain_stub_units` and `match: true` in a consistent state.

---

## Inspecting the DB (Dockerized Postgres)

Open `psql` inside the DB container:

```bash
docker compose exec -it db psql -U ${POSTGRES_USER} -d ${POSTGRES_DB}
\dt
SELECT balance_pkr FROM wallet_stub_walletstubaccount;
SELECT direction, amount_pkr FROM wallet_stub_walletstubtx ORDER BY occurred_at;
SELECT job_type, amount_units, idempotency_key FROM core_chainjob ORDER BY created_at;
SELECT balance_units FROM core_tokenbalance;
SELECT balance_units FROM chain_stub_chainstubbalance;
SELECT side, account, amount_units, ref_type FROM core_ledgerentry ORDER BY created_at;
SELECT txid,event_index,event_type,amount_units FROM core_onchainevent ORDER BY id DESC;
SELECT status,amount_pkr,payout_ref FROM core_payoutjob ORDER BY id DESC;
```

---

## Local dev without Docker (optional)

Use SQLite by setting `DB_ENGINE=sqlite` in `.env` (or unset). Then:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 8000
```

CSRF flow is identical (`/api/csrf` first).

---

## Troubleshooting

* **Bad signature (403)** on `/api/webhooks/bank`
  Ensure `X-Signature` is `hex(sha256_hmac(body, BANK_WEBHOOK_SECRET))` **of the exact body bytes**.

* **Invalid host (DisallowedHost)**
  Set `ALLOWED_HOSTS` (comma-separated) to include your client host/IP.

* **CSRF 403**
  Fetch `/api/csrf` first; send cookies + `X-CSRFToken` header; keep the same origin.

* **Ingest shows more txs than mints**
  Ingest records **credits and debits**; only **credits** mint. Webhook is preferred; ingest is kept for demo parity.

* **Reset the demo DB (Docker)**

  ```bash
  docker compose down -v && docker compose up --build
  ```

---

## Next iterations (suggested)

* Replace stubs with real adapters (bank + Stacks/Clarity), plug in **Chainhook** service mode.
* Background workers / retries, dead-letter queues, and **Temporal** for exactly-once orchestration.
* Tamper-evident ledger hashing & reconciliation alerts.
* Stronger user mapping (e.g., `UserProfile` with Stacks address), full KYC/AML gating.
