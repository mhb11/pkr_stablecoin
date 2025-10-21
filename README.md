# pkr_stablecoin — MVP (Django)

Minimal, happy-path demo of a PKR-pegged stablecoin flow:

1. **Deposit PKR** into a wallet (simulated provider).
2. **Ingest** provider transactions.
3. **Mint** the same amount of tokens (stub chain).
4. **Redeem (burn)** tokens and **debit** the wallet.

**Demo-only**: simplified security, no KYC/AML. Wallet and chain are **DB-backed stubs** for deterministic behavior and easy inspection.

---

## Why this exists

* Prove end-to-end plumbing: **provider deposit → ingest → mint** and **burn → provider debit**.
* Keep **unit conversions** and **ledger semantics** explicit and inspectable.
* Freeze an API surface you can later swap to real providers and a real chain.

---

## Stack / Concepts

* **Django + SQLite** (default)
* **Two stubs**:

  * `wallet_stub`: simulates a PKR wallet account + tx log
  * `chain_stub`: simulates an ERC-20-like balance and receipts
* **Units**: tokens use `TOKEN_DECIMALS = 6`

  * `1 PKR == 1_000_000 token units`
* **Tables to know**:

  * `wallet_stub_walletstubaccount`, `wallet_stub_walletstubtx` (provider side)
  * `core_externaltransaction` (ingested provider txs)
  * `core_chainjob` (each mint/burn job)
  * `core_tokenbalance` + `chain_stub_chainstubbalance` (app + “on-chain” balances)
  * `core_ledgerentry` (issuer vs user entries for each mint/burn)

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 8000
```

> This project keeps Django’s CSRF **enabled**. When using curl/Postman you must fetch a CSRF token first.

---

## Getting a CSRF token (curl)

```bash
# Get cookie + CSRF token (the app exposes /api/csrf)
curl -i -c cookies.txt http://localhost:8000/api/csrf
# Extract the token into a shell variable
TOKEN=$(grep csrftoken cookies.txt | awk '{print $7}' | tail -n1)
echo $TOKEN
```

> Always use the **same host/port** (e.g., `http://localhost:8000`) for both GET token and subsequent POSTs.

---

## Happy-Path Script (with **what to expect** & **what changed**)

### 1) Seed demo user + wallet

```bash
curl -X POST http://localhost:8000/api/demo/seed \
  -b cookies.txt -H "X-CSRFToken: $TOKEN"
```

**Response:**
`{ "user_id": "<uuid>", "wallet_account": "WALLET-001" }`

**DB now**

* `core_user`: 1 row (demo user)
* `wallet_stub_walletstubaccount`: `WALLET-001` with `balance_pkr = 0.00`
* `core_tokenbalance`: `balance_units = 0`

---

### 2) Simulate PKR deposit (wallet credit)

```bash
curl -X POST http://localhost:8000/api/demo/wallet/credit \
  -b cookies.txt -H "X-CSRFToken: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount_pkr":"1000.00","memo":"Deposit #1"}'
```

**Response:**
`{ "provider_tx_id": "TX-..." }`

**DB now**

* `wallet_stub_walletstubtx`: +1 row (`direction=credit`, `amount_pkr=1000.00`)
* `wallet_stub_walletstubaccount.balance_pkr` = `1000.00`
* (No token minted **yet**—that happens after ingest.)

---

### 3) Ingest provider txns (detect credit → **auto-mint**)

```bash
curl -X POST http://localhost:8000/api/ingest/wallet-transactions \
  -b cookies.txt -H "X-CSRFToken: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"since":"2025-01-01T00:00:00Z"}'
```

**Response:**
`{ "ingested": 1, "minted": 1 }`
(ingested wallet credit → minted 1,000 tokens)

**DB now**

* `core_externaltransaction`: +1 credit row (the ingested provider tx)
* `core_chainjob`: +1 row (`job_type='mint'`, `amount_units=1000000000`, `status='confirmed'`)
* `core_tokenbalance`: `1000000000`
* `chain_stub_chainstubbalance`: `1000000000`
* `core_ledgerentry`: +2 rows (issuer_token **credit** 1e9; user_token **debit** 1e9)

---

### 4) Check token balance

```bash
curl http://localhost:8000/api/balance
```

**Response:**
`{ "token_balance_units": "1000000000", "token_decimals": 6 }` (== 1,000.000000)

---

### 5) Redeem 200 PKR (burn → wallet debit) with idempotency key

```bash
KEY=$(python - <<'PY'\nimport uuid;print(uuid.uuid4())\nPY)
curl -X POST http://localhost:8000/api/redeem \
  -b cookies.txt -H "X-CSRFToken: $TOKEN" \
  -H "Idempotency-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount_units":"200000000","memo":"cash-out"}'
```

**Response:**
`{ "job_id": "...", "tx_hash": "0xBURN", "amount_units": "200000000" }`

**DB now**

* `core_chainjob`: +1 row (`job_type='burn'`, `amount_units=200000000`, `idempotency_key=$KEY`)
* `core_tokenbalance`: `800000000` (was 1e9)
* `chain_stub_chainstubbalance`: `800000000`
* `wallet_stub_walletstubtx`: +1 `debit` row for `200.00` → account balance `800.00`
* `core_ledgerentry`: +2 rows (user_token **credit** 200M; issuer_token **debit** 200M)

> **Idempotency:** re-send the exact same request + header and you will get the same `job_id/tx_hash` and **no** state change.

---

### 6) Verify balance again

```bash
curl http://localhost:8000/api/balance
```

**Response:**
`{ "token_balance_units": "800000000", "token_decimals": 6 }`

---

## “What’s going on?” — quick introspection tools

### Debug summary (optional helper endpoint)

If you added `/api/debug/summary` per the docs:

```bash
curl http://localhost:8000/api/debug/summary
```

**Expect something like:**

```json
{
  "chain_jobs": { "mints_units":"1000000000", "burns_units":"200000000", "net_units":"800000000" },
  "balances":  { "token_balance_units":"800000000", "chain_stub_units":"800000000", "match": true },
  "external_transactions_latest": [ ... wallet credits/debits you ingested ... ],
  "notes": "net_units should equal token_balance_units when everything is consistent."
}
```

### DB peeks (SQLite)

```bash
python manage.py dbshell
.tables
SELECT balance_pkr FROM wallet_stub_walletstubaccount;
SELECT direction, amount_pkr FROM wallet_stub_walletstubtx ORDER BY occurred_at;
SELECT job_type, amount_units, idempotency_key FROM core_chainjob ORDER BY created_at;
SELECT balance_units FROM core_tokenbalance;
SELECT balance_units FROM chain_stub_chainstubbalance;
SELECT side, account, amount_units, ref_type FROM core_ledgerentry ORDER BY created_at;
```

---

## Idempotency (how to test)

* First redeem:

  ```bash
  KEY=REDEEM-TEST-1
  curl -X POST http://localhost:8000/api/redeem \
    -b cookies.txt -H "X-CSRFToken: $TOKEN" \
    -H "Idempotency-Key: $KEY" \
    -H "Content-Type: application/json" \
    -d '{"amount_units":"200000000","memo":"again"}'
  ```
* Replay (same key, same body): **no new state**, same `job_id` returned.
* Different key (`REDEEM-TEST-2`): executes again (balances/ledger change).

> We also support an idempotent **manual** `/api/mint` call if you ever use it: send `Idempotency-Key` there too.

---

## Endpoints (cheat sheet)

* `POST /api/demo/seed` → create/fetch demo user + wallet
* `POST /api/demo/wallet/credit` `{amount_pkr, memo}` → simulate wallet **deposit**
* `POST /api/ingest/wallet-transactions` `{since}` → pull provider txs, **mint** credits
* `POST /api/mint` `{provider_tx_id}` → (manual) mint for a specific ingested credit
* `POST /api/redeem` `{amount_units, memo}` + `Idempotency-Key` → **burn** + wallet **debit**
* `GET /api/balance` → token units + decimals
* `GET /api/ledger` → recent issuer/user entries
* `GET /api/external-transactions` → ingested wallet txs
* `GET /api/csrf` → issue a CSRF cookie/token for curl/Postman
* (optional) `GET /api/debug/summary` → one-shot reconciliation

---

## Troubleshooting

* **403 CSRF**: fetch token via `GET /api/csrf`; use cookie jar (`-b cookies.txt`) and header `-H "X-CSRFToken: $TOKEN"`. Same host/port only.
* **No such table**: run `python manage.py makemigrations` then `python manage.py migrate`.
* **Decimal error**: ensure you’re on the version with Decimal coercion in the wallet adapter.
* **Ingest counts look odd**: ingest reports all provider txs; only `credit` mints. Re-ingest with a wide `since` to pull in wallet **debits** created by recent redeems.
* **Reset demo DB** (local only):

  ```bash
  rm db.sqlite3
  find . -path "*/migrations/*.py" -not -name "__init__.py" -delete
  python manage.py makemigrations core wallet_stub chain_stub api
  python manage.py migrate
  ```

---

## Optional: quick automated test (pytest)

```bash
pip install pytest pytest-django
cat > pytest.ini <<'INI'
[pytest]
DJANGO_SETTINGS_MODULE = pkr_stablecoin.settings
python_files = tests.py test_*.py *_tests.py
INI
```

Create `tests/test_happy_path.py` with a minimal seed→deposit→ingest→redeem flow (or use the fuller idempotency tests we discussed).
Run:

```bash
pytest -q
```

---

## Next iterations (suggested)

* More idempotency coverage (ingest webhooks), retries, and clean 4xx errors.
* Webhooks + signature verification (replace ingest polling).
* Tamper-evident ledger hashing.
* Temporal workflows (exactly-once orchestration).
* Real provider adapters (wallet + on-chain).