"""Read-only endpoints to inspect the demo state (who, balances, ledger, external txs)."""

from django.http import JsonResponse
from django.conf import settings
from django.db.models import Sum
from chain_stub.models import ChainStubBalance
from core.models import User, ChainJob, TokenBalance, LedgerEntry, ExternalTransaction


def me(request):
	"""
	GET: Return the seeded demo user's identity
	"""
	user = User.objects.get(email=settings.DEMO_USER_EMAIL)
	return JsonResponse({"user_id": str(user.id), "email": user.email, "display_name": user.display_name})


def balance(request):
	"""
	GET: Current token balance in integer units + token decimals for formatting
	"""
	user = User.objects.get(email=settings.DEMO_USER_EMAIL)
	tb = TokenBalance.objects.get(user=user)
	from django.conf import settings as s
	return JsonResponse({
		"token_balance_units": str(tb.balance_units),
		"token_decimals": getattr(s, "TOKEN_DECIMALS", 6),
	})


def ledger(request):
	"""
	GET: Recent ledger entries (issuer + user) for quick verification
	"""
	user = User.objects.get(email=settings.DEMO_USER_EMAIL)
	rows = LedgerEntry.objects.filter(user__in=[None, user]).order_by("-created_at")[:50]
	data = [
		{
			"id": str(r.id),
			"user_id": str(r.user.id) if r.user else None,
			"side": r.side,
			"account": r.account,
			"amount_units": str(r.amount_units),
			"ref_type": r.ref_type,
			"ref_id": str(r.ref_id),
			"created_at": r.created_at.isoformat(),
		}
		for r in rows
	]
	return JsonResponse(data, safe=False)


def external_txs(request):
	"""
	GET: Recently recorded wallet-provider transactions (credits/debits)
	"""
	user = User.objects.get(email=settings.DEMO_USER_EMAIL)
	# scope by user's wallet account implicitly via FK in ExternalTransaction
	rows = ExternalTransaction.objects.order_by("-recorded_at")[:50]
	data = [
		{
			"provider_tx_id": r.provider_tx_id,
			"direction": r.direction,
			"amount_pkr": f"{r.amount_pkr:.2f}",
			"memo": r.memo,
			"occurred_at": r.occurred_at.isoformat(),
			"recorded_at": r.recorded_at.isoformat(),
		}
		for r in rows
	]
	return JsonResponse(data, safe=False)


def debug_summary(request):
	# Aggregates (None when no rows → coalesce to 0)
	mints = ChainJob.objects.filter(job_type='mint').aggregate(s=Sum('amount_units'))['s'] or 0
	burns = ChainJob.objects.filter(job_type='burn').aggregate(s=Sum('amount_units'))['s'] or 0
	net = mints - burns

	# Balances (None → 0)
	tb = TokenBalance.objects.first()
	tb_units = tb.balance_units if tb else 0

	cb = ChainStubBalance.objects.first()
	cb_units = cb.balance_units if cb else 0

	# Latest external txs (wallet-side) for quick context
	ext = list(
		ExternalTransaction.objects
		.order_by('-recorded_at')
		.values('provider_tx_id', 'direction', 'amount_pkr', 'occurred_at', 'recorded_at')[:10]
	)

	return JsonResponse({
		"chain_jobs": {
			"mints_units": str(mints),
			"burns_units": str(burns),
			"net_units": str(net),
		},
		"balances": {
			"token_balance_units": str(tb_units),
			"chain_stub_units": str(cb_units),
			"match": (tb_units == cb_units),
		},
		"external_transactions_latest": ext,
		"notes": "net_units should equal token_balance_units when everything is consistent.",
	})