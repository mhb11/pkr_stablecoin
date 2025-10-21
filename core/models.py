"""Database models for the MVP.


Tables:
- User: a single seeded demo identity
- WalletAccount: link between user and the (stub) wallet provider
- ExternalTransaction: append-only feed of provider txns (credits/debits)
- TokenBalance: convenience cache of on-chain balance (authoritative source is chain)
- ChainJob: audit row for each mint/burn submitted to chain
- LedgerEntry: minimal double-entry-like record for issuer vs user token positions
"""

import uuid
from django.db import models


class User(models.Model):
	"""
	Demo user entity (one row is sufficient for the happy-path demo)
	"""
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	email = models.EmailField(unique=True)
	display_name = models.CharField(max_length=200)
	created_at = models.DateTimeField(auto_now_add=True)


class WalletAccount(models.Model):
	"""
	Maps our User to an external wallet provider account (currently stubbed)
	"""
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	provider = models.CharField(max_length=50) # 'stub-wallet'
	provider_acct = models.CharField(max_length=50) # 'WALLET-001'
	created_at = models.DateTimeField(auto_now_add=True)


class ExternalTransaction(models.Model):
	"""
	Immutable log of wallet-provider transactions we ingested.

	provider_tx_id is unique to prevent double-ingest/double-mint
	"""
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	wallet_acct = models.ForeignKey(WalletAccount, on_delete=models.CASCADE)
	provider_tx_id = models.CharField(max_length=100, unique=True)
	direction = models.CharField(max_length=10) # 'credit' | 'debit'
	amount_pkr = models.DecimalField(max_digits=18, decimal_places=2)
	memo = models.TextField(blank=True)
	occurred_at = models.DateTimeField()
	recorded_at = models.DateTimeField(auto_now_add=True)


class TokenBalance(models.Model):
	"""
	Cached token balance in integer units for quick reads (demo convenience)
	"""
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	balance_units = models.BigIntegerField(default=0)


class ChainJob(models.Model):
	"""
	Tracks each mint/burn call made to the chain adapter and its receipt
	"""
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	user = models.ForeignKey(User, on_delete=models.CASCADE)
	job_type = models.CharField(max_length=10) # 'mint' | 'burn'
	amount_units = models.BigIntegerField()
	ref_external_tx = models.ForeignKey(ExternalTransaction, null=True, blank=True, on_delete=models.SET_NULL)
	tx_hash = models.CharField(max_length=100, blank=True)
	status = models.CharField(max_length=20) # 'submitted'|'confirmed'
	created_at = models.DateTimeField(auto_now_add=True)
	confirmed_at = models.DateTimeField(null=True, blank=True)
	idempotency_key = models.CharField(max_length=64, null=True, blank=True, unique=True) # unique idempotency key


class LedgerEntry(models.Model):
	"""
	Simplified ledger entries for issuer_token and user_token positions.

	Note: This is not a full accounting system; it’s enough to explain flows.
	"""
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
	side = models.CharField(max_length=10) # 'debit' | 'credit'
	account = models.CharField(max_length=50) # 'issuer_token' | 'user_token'
	amount_units = models.BigIntegerField()
	ref_type = models.CharField(max_length=20) # 'mint'|'burn'
	ref_id = models.UUIDField()
	created_at = models.DateTimeField(auto_now_add=True)