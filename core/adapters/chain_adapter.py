"""Adapter over the local chain stub

In production, this would submit signed transactions to a real blockchain and check
finality. Here we mutate a DB table to simulate balances and receipts.
"""

from chain_stub.models import ChainStubBalance


class ChainAdapter:
	"""
	Minimal mint/burn/balance calls returning confirmed receipts.
	Accepts optional idempotency_key so the service layer doesn't change later.
	"""
	@staticmethod
	def mint(user_id, amount_units: int, idempotency_key: str | None = None):
		"""
		Simulate a confirmed on-chain mint by incrementing the per-user balance.
		idempotency_key is ignored in the stub but kept for future Stacks integration.
		"""
		bal, _ = ChainStubBalance.objects.get_or_create(user_id=user_id, defaults={"balance_units": 0})
		bal.balance_units += int(amount_units)
		bal.save(update_fields=["balance_units"])
		return {"tx_hash": "0xMINT", "status": "confirmed"}

	@staticmethod
	def burn(user_id, amount_units: int, idempotency_key: str | None = None):
		"""
		Simulate a confirmed burn by decrementing the per-user balance.
		idempotency_key is ignored in the stub but kept for future Stacks integration.
		"""
		bal, _ = ChainStubBalance.objects.get_or_create(user_id=user_id, defaults={"balance_units": 0})
		bal.balance_units -= int(amount_units)
		bal.save(update_fields=["balance_units"])
		return {"tx_hash": "0xBURN", "status": "confirmed"}

	@staticmethod
	def get_balance(user_id) -> int:
		bal, _ = ChainStubBalance.objects.get_or_create(user_id=user_id, defaults={"balance_units": 0})
		return int(bal.balance_units)