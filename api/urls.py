"""Public API surface for the MVP demo.

- /demo/* endpoints: convenience helpers to seed and simulate deposits
- /ingest/wallet-transactions: pulls provider txns and triggers mint for credits
- /redeem: burns tokens and debits wallet PKR
- /balance, /ledger, /external-transactions: read-only views for verification
"""

from django.urls import path
from .views_demo import seed, wallet_credit
from .views_ops import ingest_wallet_txs, mint, redeem, health, csrf, bank_webhook, stacks_chainhook_webhook
from .views_read import me, balance, ledger, external_txs, debug_summary


urlpatterns = [
	path("health", health),
	path("demo/seed", seed),
	path("demo/wallet/credit", wallet_credit),
	path("ingest/wallet-transactions", ingest_wallet_txs),
	path("mint", mint),
	path("csrf", csrf),
	path("redeem", redeem),
	path("me", me),
	path("debug/summary", debug_summary),
	path("balance", balance),
	path("ledger", ledger),
	path("external-transactions", external_txs),
	path("webhooks/bank", bank_webhook, name="bank_webhook"),
    path("webhooks/stacks", stacks_chainhook_webhook, name="stacks_chainhook_webhook"),
]