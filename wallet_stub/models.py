"""Deterministic in-process wallet provider.

Stores a single account (WALLET-001) and an append-only tx log. Used to simulate
credits (deposits) and debits (payouts) without network calls.
"""

import uuid
from django.db import models
from django.utils.timezone import now


class WalletStubAccount(models.Model):
	"""
	Represents the external wallet account backing the PKR reserve (stub)
	"""
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	account_id = models.CharField(max_length=50, unique=True) # e.g. WALLET-001
	balance_pkr = models.DecimalField(max_digits=18, decimal_places=2, default=0)


def gen_provider_tx_id():
	# Named function = migration-friendly
	return f"TX-{uuid.uuid4().hex[:8]}"


class WalletStubTx(models.Model):
	"""
	Append-only list of provider transactions with unique provider_tx_id
	"""
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	account = models.ForeignKey(WalletStubAccount, on_delete=models.CASCADE)
	provider_tx_id = models.CharField(max_length=100, unique=True, default=gen_provider_tx_id)
	direction = models.CharField(max_length=10)  # 'credit' | 'debit'
	amount_pkr = models.DecimalField(max_digits=18, decimal_places=2)
	memo = models.TextField(blank=True)
	occurred_at = models.DateTimeField(default=now)