"""Adapter over the local wallet stub.

In production, this would call a real wallet provider  via HTTP with
auth, retries, and signatures. Here we call the stub’s ORM models directly for
repeatable, deterministic tests.
"""

from decimal import Decimal
from datetime import datetime
from wallet_stub.models import WalletStubAccount, WalletStubTx
from django.utils.timezone import is_naive, make_aware


class WalletAdapter:
	"""
	Pure functions that wrap wallet stub operations for credits/debits/reads
	"""
	
	provider_name = "stub-wallet"


	@staticmethod
	def ensure_account(account_id: str):
		acct, _ = WalletStubAccount.objects.get_or_create(
            account_id=account_id,
            # Decimal(str(value)) guarantees we’re doing real decimal math (no float, no strings), so 0.00 + 1000.00 → 1000.00 as expected.
            defaults={"balance_pkr": Decimal("0.00")}
        )
		return acct


	@staticmethod
	def credit(account_id: str, amount_pkr: str, memo: str) -> str:
		"""
		Record a provider-facing credit (basically a simulated deposit) and update the stub balance.
		"""
		acct = WalletAdapter.ensure_account(account_id)
		# Coerce to Decimal explicitly
		amt = Decimal(str(amount_pkr))
		tx = WalletStubTx.objects.create(
			account=acct,
			direction="credit",
			amount_pkr=amt,
			memo=memo,
		)
		# update balance (ensure Decimal + Decimal)
		acct.balance_pkr = (acct.balance_pkr or Decimal("0")) + tx.amount_pkr
		acct.save(update_fields=["balance_pkr"])
		return tx.provider_tx_id


	@staticmethod
	def debit(account_id: str, amount_pkr: str, memo: str) -> str:
		acct = WalletAdapter.ensure_account(account_id)
		amt = Decimal(str(amount_pkr))
		tx = WalletStubTx.objects.create(
			account=acct,
			direction="debit",
			amount_pkr=amt,
			memo=memo,
		)
		acct.balance_pkr = (acct.balance_pkr or Decimal("0")) - tx.amount_pkr
		acct.save(update_fields=["balance_pkr"])
		return tx.provider_tx_id


	@staticmethod
	def balance(account_id: str) -> str:
		acct = WalletAdapter.ensure_account(account_id)
		# Format only when returning as text
		return f"{acct.balance_pkr:.2f}"


	@staticmethod
	def list_transactions(account_id: str, since_iso: str):
		"""
		Return provider-shaped dicts so ingest code looks like real-world parsing
		"""
		acct = WalletAdapter.ensure_account(account_id)
		if since_iso:
			dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
			since_dt = make_aware(dt) if is_naive(dt) else dt
			qs = WalletStubTx.objects.filter(account=acct, occurred_at__gte=since_dt).order_by("occurred_at")
		else:
			qs = WalletStubTx.objects.filter(account=acct).order_by("occurred_at")
		return [
			{
				"provider_tx_id": tx.provider_tx_id,
				"direction": tx.direction,
				"amount_pkr": f"{tx.amount_pkr:.2f}",
				"memo": tx.memo,
				"occurred_at": tx.occurred_at.isoformat().replace("+00:00", "Z"),
			}
			for tx in qs
		]