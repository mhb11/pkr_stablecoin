# pkr_stablecoin — MVP (Django)

Minimal, **happy-path** demo of a PKR-pegged (Pakistani Rupee) stablecoin flow:

1. **Deposit PKR** into a wallet (simulated provider).
2. **Ingest** provider transactions.
3. **Mint** the same amount of tokens (stub “chain”).
4. **Redeem (burn)** tokens and **debit** the wallet.

**Demo-only**: simplified security, no KYC/AML. Wallet and chain are **DB-backed stubs** for deterministic behavior and easy inspection.

---

## Why this exists

* Prove end-to-end plumbing: **provider deposit → ingest → mint** and **burn → provider debit**.
* Keep **unit conversions** and **ledger semantics** explicit & inspectable.
* Freeze an API surface we can later swap to real providers and a real chain.

---

## Architecture & Concepts

* **Django API**, **PostgreSQL (via Docker)** by default. (SQLite supported for local no-Docker dev.)
* **Stubs**:

  * `wallet_stub`: simulates a PKR wallet account + tx log.
  * `chain_stub`: simulates an ERC-20-like balance and receipts.
* **Units**: tokens use `TOKEN_DECIMALS = 6` → `1 PKR == 1_000_000 token units`.
* **Core tables**:

  * Provider side: `wallet_stub_walletstubaccount`, `wallet_stub_walletstubtx`
  * Ingested provider txs: `core_externaltransaction`
  * Chain jobs: `core_chainjob` (each mint/burn)
  * Balances: `core_tokenbalance` (app), `chain_stub_chainstubbalance` (“on-chain”)
  * Ledger: `core_ledgerentry` (issuer vs user entries per mint/burn)

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

`.env` defaults (safe for local demo):

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
```

> ⚠️ If you previously exported any `POSTGRES_*` vars in your shell, **unset** them; shell env overrides `.env`.

2. **Start the stack**

```bash
docker compose up --build
```

This brings up Postgres 15 and the Django app (gunicorn), applies migrations, and exposes the API at `http://localhost:8000`.

3. **Health check**

```bash
curl http://localhost:8000/api/health
# {"ok": true}
```

---

## CSRF (curl/Postman)

This project keeps Django’s CSRF **enabled**. For POSTs:

```bash
# Get cookie + CSRF token
curl -s -c cookies.txt http://localhost:8000/api/csrf > /dev/null
TOKEN=$(grep csrftoken cookies.txt | awk '{print $7}' | tail -n1)
```

> Always use the **same origin** (e.g., `http://localhost:8000`) for token fetch and subsequent POSTs.

---

## Happy-Path Walkthrough (with expected results)

### 1) Seed demo user + wallet

```bash
curl -X POST http://localhost:8000/api/demo/seed \
  -b cookies.txt -H "X-CSRFToken: $TOKEN"
```

**Response** → `{ "user_id": "<uuid>", "wallet_account": "WALLET-001" }`
DB: `core_user` (1 row), `wallet_stub_walletstubaccount` balance `0.00`, `core_tokenbalance` `0`.

---

### 2) Deposit 1000 PKR (provider credit)

```bash
curl -X POST http://localhost:8000/api/demo/wallet/credit \
  -b cookies.txt -H "X-CSRFToken: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount_pkr":"1000.00","memo":"Deposit #1"}'
```

**Response** → `{ "provider_tx_id": "TX-..." }`
DB: `wallet_stub_walletstubtx` +1 (`credit`, 1000.00); account balance `1000.00`. **No mint yet**.

---

### 3) Ingest (auto-mints credits)

```bash
curl -X POST http://localhost:8000/api/ingest/wallet-transactions \
  -b cookies.txt -H "X-CSRFToken: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"since":"2025-01-01T00:00:00Z"}'
```

**Response** → `{ "ingested": 1, "minted": 1 }`
DB:

* `core_externaltransaction` +1 (credit)
* `core_chainjob` +1 mint (`amount_units=1000000000`, `status=confirmed`)
* `core_tokenbalance` `1000000000`
* `chain_stub_chainstubbalance` `1000000000`
* `core_ledgerentry` +2 (issuer_token **credit** 1e9; user_token **debit** 1e9)

---

### 4) Check token balance

```bash
curl http://localhost:8000/api/balance
```

**Response** → `{ "token_balance_units": "1000000000", "token_decimals": 6 }` (== 1,000.000000)

---

### 5) Redeem 200 PKR (burn + wallet debit) with idempotency key

```bash
KEY=$(python - <<'PY'\nimport uuid;print(uuid.uuid4())\nPY)

curl -X POST http://localhost:8000/api/redeem \
  -b cookies.txt -H "X-CSRFToken: $TOKEN" \
  -H "Idempotency-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount_units":"200000000","memo":"cash-out"}'
```

**Response** → `{ "job_id": "...", "tx_hash": "0xBURN", "amount_units": "200000000" }`
DB:

* `core_chainjob` +1 burn (`amount_units=200000000`, `idempotency_key=$KEY`)
* `core_tokenbalance` `800000000`
* `chain_stub_chainstubbalance` `800000000`
* `wallet_stub_walletstubtx` +1 debit `200.00` → wallet `800.00`
* `core_ledgerentry` +2 (user_token **credit** 200M; issuer_token **debit** 200M)

**Idempotency behavior**: re-send the same POST (same body + same `Idempotency-Key`) → **same** `job_id`, **no** state change.

---

### 6) Balance again

```bash
curl http://localhost:8000/api/balance
```

**Response** → `{ "token_balance_units": "800000000", "token_decimals": 6 }`

---

## One-shot reconciliation

```bash
curl http://localhost:8000/api/debug/summary
```

Expect:

```json
{
  "chain_jobs": {"mints_units":"1000000000","burns_units":"200000000","net_units":"800000000"},
  "balances": {"token_balance_units":"800000000","chain_stub_units":"800000000","match":true},
  "external_transactions_latest": [...],
  "notes": "net_units should equal token_balance_units when everything is consistent."
}
```

---

## Endpoints (cheat sheet)

* `GET  /api/csrf` → issue CSRF cookie/token
* `POST /api/demo/seed` → create/fetch demo user + wallet
* `POST /api/demo/wallet/credit` `{amount_pkr, memo}` → simulate wallet **deposit**
* `POST /api/ingest/wallet-transactions` `{since}` → pull provider txs, **mint** credits
* `POST /api/mint` `{provider_tx_id}` → (manual) mint a specific ingested credit
* `POST /api/redeem` `{amount_units, memo}` + `Idempotency-Key` → **burn** + wallet **debit**
* `GET  /api/balance` → token units + decimals
* `GET  /api/ledger` → recent issuer/user ledger entries
* `GET  /api/external-transactions` → ingested wallet txs
* (optional) `GET /api/debug/summary` → single-shot reconciliation

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

* **Web container can’t reach DB (tries `localhost`)**
  Inside containers, `POSTGRES_HOST` must be **`db`** (the service name), not `localhost`.
  Check:

  ```bash
  docker compose config | grep POSTGRES_HOST -n
  docker compose exec web env | grep POSTGRES_HOST
  ```

  If it shows `localhost`, unset any shell-exported `POSTGRES_HOST` and/or add `env_file: .env` in compose, or use defaults in compose: `POSTGRES_HOST: ${POSTGRES_HOST:-db}`.

* **CSRF 403**
  Fetch `/api/csrf` first; send cookies and `X-CSRFToken` header; keep the same origin.

* **Ingest shows more txs than mints**
  Ingest records **credits and debits**; only **credits** mint. Re-ingest with a wide `since` to see wallet **debits** created by redeems.

* **Reset the demo DB (Docker)**

  ```bash
  docker compose down -v && docker compose up --build
  ```

* **Healthcheck failing due to missing `curl`**
  The Dockerfile installs `curl`. If you change the base image, re-add `curl` or switch the healthcheck to a Python snippet.

---

## Next iterations (suggested)

* Broader idempotency (ingest webhooks), retries, clean 4xx errors.
* Webhooks + signature verification (replace ingest polling).
* Tamper-evident ledger hashing.
* Temporal workflows (exactly-once orchestration).
* Real provider adapters (wallet + on-chain).