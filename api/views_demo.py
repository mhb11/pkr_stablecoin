"""Demo helpers: seed a user and push a simulated wallet credit."""

import json
from django.http import JsonResponse, HttpResponseBadRequest
from core.services import DemoServices


def seed(request):
	"""
	POST: Create/fetch the demo user + wallet account for this run
	"""
	if request.method != "POST":
		return HttpResponseBadRequest("POST only")
	user, wa = DemoServices.seed_demo_user()
	return JsonResponse({"user_id": str(user.id), "wallet_account": wa.provider_acct})


def wallet_credit(request):
	"""
	POST: Simulate an external PKR deposit (credit) into the wallet stub
	"""
	if request.method != "POST":
		return HttpResponseBadRequest("POST only")
	body = json.loads(request.body or b"{}")
	amount_pkr = body.get("amount_pkr")
	memo = body.get("memo", "seed")
	if not amount_pkr:
		return HttpResponseBadRequest("amount_pkr required")
	provider_tx_id = DemoServices.wallet_credit(amount_pkr, memo)
	return JsonResponse({"provider_tx_id": provider_tx_id}, status=201)