"""Business orchestration for the demo.

This module coordinates: seed → wallet credit → ingest → mint, and redeem flows.
Critical mutations are wrapped in @transaction.atomic to keep state consistent.
"""

from datetime import datetime
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.conf import settings

from .models import (
	User, WalletAccount, ExternalTransaction, TokenBalance, ChainJob, LedgerEntry
)
from .constants import pkr_to_units, units_to_pkr
from .adapters.wallet_adapter import WalletAdapter
from .adapters.chain_adapter import ChainAdapter

# Logical token accounts for the simplified ledger.
ISSUER_TOKEN = "issuer_token"
USER_TOKEN = "user_token"


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
		receipt = ChainAdapter.mint(user.id, amount_units)

		try:
			job = ChainJob.objects.create(
				user=user,
				job_type="mint",
				amount_units=amount_units,
				ref_external_tx=et,
				tx_hash=receipt["tx_hash"],
				status=receipt["status"],
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