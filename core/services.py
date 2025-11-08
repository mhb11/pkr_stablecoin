"""Business orchestration for the demo.

This module coordinates: seed → wallet credit → ingest → mint, and redeem flows.
Critical mutations are wrapped in @transaction.atomic to keep state consistent.
"""
from datetime import datetime
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.conf import settings

from .models import (
	User, WalletAccount, ExternalTransaction, ExternalTransactionStatus, OnchainEvent, PayoutJob, PayoutJobStatus, TokenBalance, ChainJob, LedgerEntry
)
from .constants import pkr_to_units, units_to_pkr
from .adapters.wallet_adapter import WalletAdapter
from .adapters.chain_adapter import ChainAdapter

# Logical token accounts for the simplified ledger.
ISSUER_TOKEN = "issuer_token"
USER_TOKEN = "user_token"


@transaction.atomic
def perform_mint_for_external_tx(external_tx: ExternalTransaction, *, user, idempotency_key: str) -> str:
	"""
	Enforces: mint only after a *recorded* bank tx (external_tx).
	Also mirrors the mint in local cache & ledger so debug/summary matches on-chain.
	Returns chain tx hash (stub or real).
	"""
	if external_tx.status == ExternalTransactionStatus.MINTED:
		return "already-minted"

	# Convert PKR -> base units
	amount_units = pkr_to_units(external_tx.amount_pkr)
	if amount_units <= 0:
		raise ValueError("Amount must be > 0")

	# Optional ceilings
	# if external_tx.amount_pkr > settings.MAX_SINGLE_MINT_PKR: raise ValueError("Over ceiling")

	# Call chain
	chain = ChainAdapter()
	receipt = chain.mint(user_id=user.id, amount_units=amount_units, idempotency_key=idempotency_key)

	# Normalize receipt for both dict/obj stubs
	tx_hash = getattr(receipt, "tx_hash", None) or (receipt.get("tx_hash") if isinstance(receipt, dict) else None) or "stub-tx-hash"
	status  = getattr(receipt, "status",  None) or (receipt.get("status")  if isinstance(receipt, dict) else "confirmed")

	# Record a ChainJob (idempotent on idempotency_key)
	try:
		job = ChainJob.objects.create(
			user=user,
			job_type="mint",
			amount_units=amount_units,
			ref_external_tx=external_tx,
			tx_hash=tx_hash,
			status=status,
			idempotency_key=idempotency_key,
		)
	except IntegrityError:
		# Another request with same key raced us; fetch the existing job
		job = ChainJob.objects.get(idempotency_key=idempotency_key)

	# Update token balance cache
	tb, _ = TokenBalance.objects.select_for_update().get_or_create(user=user, defaults={"balance_units": 0})
	tb.balance_units += amount_units
	tb.save(update_fields=["balance_units"])

	# Write ledger entries (issuer credit, user debit)
	LedgerEntry.objects.bulk_create([
		LedgerEntry(user=None, side="credit", account=ISSUER_TOKEN, amount_units=amount_units, ref_type="mint", ref_id=job.id),
		LedgerEntry(user=user, side="debit",  account=USER_TOKEN,   amount_units=amount_units, ref_type="mint", ref_id=job.id),
	])

	# Flip the bank ET status after success
	external_tx.status = ExternalTransactionStatus.MINTED
	external_tx.save(update_fields=["status"])

	return tx_hash


@transaction.atomic
def process_payout_for_onchain_event(event: OnchainEvent, *, payout_method: "UserPayoutMethod|None" = None) -> PayoutJob:
	"""
	Called after a verified on-chain BURN event (via Chainhook webhook).
	Creates or updates a PayoutJob and attempts bank payout immediately (stub).
	"""
	amount_pkr = units_to_pkr(event.amount_units)

	job, _ = PayoutJob.objects.get_or_create(
		onchain_event=event,
		defaults=dict(user=event.user, amount_pkr=amount_pkr, status=PayoutJobStatus.PENDING),
	)

	# Lock the row for this transaction to avoid concurrent payout
	job = PayoutJob.objects.select_for_update().get(pk=job.pk)

	if job.status == PayoutJobStatus.SUCCESS:
		return job

	try:
		job.attempts += 1
		# ceilings (optional)
		# if job.amount_pkr > settings.MAX_SINGLE_PAYOUT_PKR: raise ValueError("Over ceiling")

		# Simulate bank payout. In real life, call bank API; store bank reference in payout_ref.

		wa = WalletAccount.objects.get(user=event.user)
		payout_ref = WalletAdapter.debit(wa.provider_acct, f"{amount_pkr:.2f}", f"payout for {event.txid}")

		job.payout_ref = str(payout_ref) if payout_ref else ""
		job.status = PayoutJobStatus.SUCCESS
		job.last_error = ""
		job.save(update_fields=["payout_ref","status","last_error","attempts","updated_at"])

		# Mark event consumed
		if not event.consumed_at:
			event.consumed_at = timezone.now()
			event.save(update_fields=["consumed_at"])

		return job

	except Exception as e:
		# Decide retryable vs final based on exception types; keep it retryable for MVP
		job.status = PayoutJobStatus.FAILED_RETRYABLE
		job.last_error = str(e)
		job.save(update_fields=["status","last_error","attempts","updated_at"])
		return job


class DemoServices:

	@staticmethod
	@transaction.atomic
	def seed_demo_user():
		"""
		Create (or fetch) the demo user, wallet account, and token balance row
		"""
		user, _ = User.objects.get_or_create(email=settings.DEMO_USER_EMAIL, defaults={"display_name": "Demo User"})
		wa, _ = WalletAccount.objects.get_or_create(user=user, provider="stub-wallet", provider_acct="WALLET-001")
		TokenBalance.objects.get_or_create(user=user, defaults={"balance_units": 0})
		return user, wa


	@staticmethod
	def wallet_credit(amount_pkr: str, memo: str):
		"""
		Simulate an external deposit into the wallet provider (stub)
		"""
		_, wa = DemoServices.seed_demo_user()
		provider_tx_id = WalletAdapter.credit(wa.provider_acct, amount_pkr, memo)
		return provider_tx_id

	@staticmethod
	@transaction.atomic
	def ingest_since(since_iso: str):
		"""
		Fetch provider txns since timestamp, store new ones, and auto-mint credits.

		Idempotence: ensured by ExternalTransaction.provider_tx_id uniqueness.
		"""
		user, wa = DemoServices.seed_demo_user()
		txs = WalletAdapter.list_transactions(wa.provider_acct, since_iso)
		ingested = 0
		minted = 0
		for t in txs:
			if not ExternalTransaction.objects.filter(provider_tx_id=t["provider_tx_id"]).exists():
				et = ExternalTransaction.objects.create(
					wallet_acct=wa,
					provider_tx_id=t["provider_tx_id"],
					direction=t["direction"],
					amount_pkr=t["amount_pkr"],
					memo=t.get("memo", ""),
					occurred_at=datetime.fromisoformat(t["occurred_at"].replace("Z", "+00:00")),
				)
				ingested += 1
				if et.direction == "credit":
					DemoServices.mint_from_provider_tx(user, et)
					minted += 1
		return {"ingested": ingested, "minted": minted}

	@staticmethod
	@transaction.atomic
	def mint_from_provider_tx(user: User, et: ExternalTransaction, idempotency_key: str | None = None):
		"""
		Convert a credited PKR amount into token units and mint on the chain stub.

		Also updates TokenBalance and writes two ledger entries (issuer credit, user debit).
		"""
		# If a key was provided and this job already exists, return it without side-effects
		if idempotency_key:
			existing = ChainJob.objects.filter(idempotency_key=idempotency_key).first()
			if existing:
				return existing

		amount_units = pkr_to_units(str(et.amount_pkr))
		chain = ChainAdapter()
		receipt = chain.mint(user_id=user.id, amount_units=amount_units, idempotency_key=idempotency_key)
		tx_hash = getattr(receipt, "tx_hash", None) or (receipt.get("tx_hash") if isinstance(receipt, dict) else None)
		status  = getattr(receipt, "status",  None) or (receipt.get("status")  if isinstance(receipt, dict) else "confirmed")

		try:
			job = ChainJob.objects.create(
				user=user,
				job_type="mint",
				amount_units=amount_units,
				ref_external_tx=et,
				tx_hash=tx_hash or "stub-tx-hash",
				status=status,
				idempotency_key=idempotency_key,
			)
		except IntegrityError:
			# Lost a race creating the job with the same idempotency key; return the existing one
			if idempotency_key:
				return ChainJob.objects.get(idempotency_key=idempotency_key)
			raise

		tb = TokenBalance.objects.select_for_update().get(user=user)
		tb.balance_units += amount_units
		tb.save(update_fields=["balance_units"])
		
		# ledger (issuer credit, user debit)
		LedgerEntry.objects.bulk_create([
			LedgerEntry(user=None, side="credit", account=ISSUER_TOKEN, amount_units=amount_units, ref_type="mint", ref_id=job.id),
			LedgerEntry(user=user, side="debit", account=USER_TOKEN, amount_units=amount_units, ref_type="mint", ref_id=job.id),
		])
		return job

	@staticmethod
	@transaction.atomic
	def redeem(user: User, amount_units: int, memo: str, idempotency_key: str | None = None):
		"""
		Burn tokens, then debit equivalent PKR from the wallet stub.
		Order (demo): burn → ledger entries → wallet debit

		TODO: In production, add retries/compensation logic
		"""
		# If a key was provided and this job already exists, return it without side-effects
		if idempotency_key:
			existing = ChainJob.objects.filter(idempotency_key=idempotency_key).first()
			if existing:
				return existing

		tb = TokenBalance.objects.select_for_update().get(user=user)
		if tb.balance_units < amount_units:
			# Convert assertion into a clean application error
			raise ValidationError("insufficient_balance")

		receipt = ChainAdapter.burn(user.id, amount_units)

		try:
			job = ChainJob.objects.create(
				user=user,
				job_type="burn",
				amount_units=amount_units,
				tx_hash=receipt["tx_hash"],
				status=receipt["status"],
				idempotency_key=idempotency_key,
			)
		except IntegrityError:
			# If two concurrent requests used the same key, return the existing one
			if idempotency_key:
				return ChainJob.objects.get(idempotency_key=idempotency_key)
			raise

		tb.balance_units -= amount_units
		tb.save(update_fields=["balance_units"])
		
		# ledger (user credit, issuer debit)

		LedgerEntry.objects.bulk_create([
			LedgerEntry(user=user, side="credit", account=USER_TOKEN,   amount_units=amount_units, ref_type="burn", ref_id=job.id),
			LedgerEntry(user=None, side="debit",  account=ISSUER_TOKEN, amount_units=amount_units, ref_type="burn", ref_id=job.id),
		])
		
		
		# debit PKR from wallet (simulate payout)
		wa = WalletAccount.objects.get(user=user)
		amount_pkr = f"{units_to_pkr(amount_units):.2f}"
		WalletAdapter.debit(wa.provider_acct, amount_pkr, memo or "redeem")
		return job