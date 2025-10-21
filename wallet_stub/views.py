"""HTTP endpoints for the wallet stub (optional to call directly in this MVP).

The adapters use ORM access for determinism; these endpoints are here to mirror
what a real provider might expose (balance, transactions, credit, debit).
"""

import json
from django.http import JsonResponse, HttpResponseBadRequest
from .models import WalletStubAccount, WalletStubTx


def balance(request):
	"""
	GET: Current PKR balance of WALLET-001
	"""
	acct = WalletStubAccount.objects.get(account_id="WALLET-001")
	return JsonResponse({"balance_pkr": f"{acct.balance_pkr:.2f}"})


def transactions(request):
	"""
	GET: Chronological list of provider txns for WALLET-001
	"""
	acct = WalletStubAccount.objects.get(account_id="WALLET-001")
	qs = WalletStubTx.objects.filter(account=acct).order_by("occurred_at")
	data = [
		{
			"provider_tx_id": tx.provider_tx_id,
			"direction": tx.direction,
			"amount_pkr": f"{tx.amount_pkr:.2f}",
			"memo": tx.memo,
			"occurred_at": tx.occurred_at.isoformat().replace("+00:00", "Z"),
		}
		for tx in qs
	]
	return JsonResponse(data, safe=False)


def credit(request):
	"""
	POST: Credit WALLET-001 by amount_pkr (simulated deposit)
	"""
	if request.method != "POST":
		return HttpResponseBadRequest("POST only")
	body = json.loads(request.body or b"{}")
	amount_pkr = body.get("amount_pkr")
	memo = body.get("memo", "seed")
	if not amount_pkr:
		return HttpResponseBadRequest("amount_pkr required")
	acct, _ = WalletStubAccount.objects.get_or_create(account_id="WALLET-001", defaults={"balance_pkr": 0})
	tx = WalletStubTx.objects.create(account=acct, direction="credit", amount_pkr=amount_pkr, memo=memo)
	acct.balance_pkr = acct.balance_pkr + tx.amount_pkr
	acct.save(update_fields=["balance_pkr"])
	return JsonResponse({"provider_tx_id": tx.provider_tx_id}, status=201)


def debit(request):
	"""
	POST: Debit WALLET-001 by amount_pkr (simulated payout)
	"""
	if request.method != "POST":
		return HttpResponseBadRequest("POST only")
	body = json.loads(request.body or b"{}")
	amount_pkr = body.get("amount_pkr")
	memo = body.get("memo", "redeem")
	if not amount_pkr:
		return HttpResponseBadRequest("amount_pkr required")
	acct = WalletStubAccount.objects.get(account_id="WALLET-001")
	tx = WalletStubTx.objects.create(account=acct, direction="debit", amount_pkr=amount_pkr, memo=memo)
	acct.balance_pkr = acct.balance_pkr - tx.amount_pkr
	acct.save(update_fields=["balance_pkr"])
	return JsonResponse({"provider_tx_id": tx.provider_tx_id}, status=201)