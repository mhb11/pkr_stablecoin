"""Database models for the MVP.


Tables:
- User: a single seeded demo identity
- WalletAccount: link between user and the (stub) wallet provider
- ExternalTransactionStatus
- ExternalTransaction: append-only feed of provider txns (credits/debits)
- OnchainEvent
- PayoutJobStatus
- PayoutJob
- UserPayoutMethod
- ReconciliationRun
- TokenBalance: convenience cache of on-chain balance (authoritative source is chain)
- ChainJob: audit row for each mint/burn submitted to chain
- LedgerEntry: minimal double-entry-like record for issuer vs user token positions
"""

import uuid
from django.db import models
from django.conf import settings


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


class ExternalTransactionStatus(models.TextChoices):
	RECEIVED = "RECEIVED", "Received"
	MINTED = "MINTED", "Minted"
	IGNORED = "IGNORED", "Ignored"


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
	status = models.CharField(max_length=16, choices=ExternalTransactionStatus.choices, default=ExternalTransactionStatus.RECEIVED)

	class Meta:
		indexes = [
			models.Index(fields=["provider_tx_id"]),
		]


class OnchainEvent(models.Model):
	"""
	Idempotent record of on-chain events (e.g., burns), so we never double-pay.
	Uniqueness: (txid, event_index)
	"""
	CHAIN_CHOICES = (("stacks-testnet", "Stacks Testnet"), ("stacks-mainnet", "Stacks Mainnet"))
	EVENT_TYPES = (("burn", "Burn"), ("mint", "Mint"))

	id = models.BigAutoField(primary_key=True)
	chain = models.CharField(max_length=32, choices=CHAIN_CHOICES, default="stacks-testnet")
	txid = models.CharField(max_length=128)
	event_index = models.IntegerField()
	event_type = models.CharField(max_length=16, choices=EVENT_TYPES)
	user = models.ForeignKey("User", on_delete=models.PROTECT, related_name="onchain_events")
	amount_units = models.BigIntegerField()  # token base units (6 decimals)
	asset_identifier = models.CharField(max_length=255, blank=True, default="")
	seen_at = models.DateTimeField(auto_now_add=True)
	consumed_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		unique_together = (("txid", "event_index"),)
		indexes = [
			models.Index(fields=["txid", "event_index"]),
		]


class PayoutJobStatus(models.TextChoices):
	PENDING = "PENDING", "Pending"
	SUCCESS = "SUCCESS", "Success"
	FAILED_RETRYABLE = "FAILED_RETRYABLE", "Failed (Retryable)"
	FAILED_FINAL = "FAILED_FINAL", "Failed (Final)"


class PayoutJob(models.Model):
	"""
	A bank payout initiated because of a *verified on-chain burn event*.
	"""
	id = models.BigAutoField(primary_key=True)
	onchain_event = models.OneToOneField("OnchainEvent", on_delete=models.PROTECT, related_name="payout_job")
	user = models.ForeignKey("User", on_delete=models.PROTECT, related_name="payout_jobs")
	amount_pkr = models.DecimalField(max_digits=18, decimal_places=2)
	payout_ref = models.CharField(max_length=128, blank=True, default="")
	status = models.CharField(max_length=24, choices=PayoutJobStatus.choices, default=PayoutJobStatus.PENDING)
	attempts = models.IntegerField(default=0)
	last_error = models.TextField(blank=True, default="")
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)


class UserPayoutMethod(models.Model):
	"""
	Where to send the user's fiat.
	"""
	METHOD_TYPES = (("IBAN", "IBAN"), ("MOBILE_WALLET", "Mobile Wallet"))
	id = models.BigAutoField(primary_key=True)
	user = models.ForeignKey("User", on_delete=models.CASCADE, related_name="payout_methods")
	method_type = models.CharField(max_length=16, choices=METHOD_TYPES)
	iban = models.CharField(max_length=64, blank=True, default="")
	mobile_wallet_id = models.CharField(max_length=64, blank=True, default="")
	label = models.CharField(max_length=64, blank=True, default="")
	created_at = models.DateTimeField(auto_now_add=True)


class ReconciliationRun(models.Model):
	"""
	Daily snapshot for supply vs bank reserves.
	"""
	id = models.BigAutoField(primary_key=True)
	as_of_date = models.DateField(unique=True)
	bank_reserve_balance_pkr = models.DecimalField(max_digits=20, decimal_places=2)
	total_onchain_supply_units = models.BigIntegerField()
	pending_payouts_pkr = models.DecimalField(max_digits=20, decimal_places=2)
	ok = models.BooleanField(default=True)
	notes = models.TextField(blank=True, default="")
	created_at = models.DateTimeField(auto_now_add=True)


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