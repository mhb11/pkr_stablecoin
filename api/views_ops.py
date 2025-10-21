"""Operational endpoints that move the system forward (ingest/mint/redeem)."""

import json
from django.http import JsonResponse, HttpResponseBadRequest
from django.core.exceptions import ValidationError
from django.conf import settings
from core.services import DemoServices
from core.models import ExternalTransaction, User
from django.middleware.csrf import get_token


def health(request):
	return JsonResponse({"ok": True})


def csrf(request):
	# Forces creation/rotation of the CSRF token AND sets 'csrftoken' cookie
	return JsonResponse({"csrftoken": get_token(request)})


def ingest_wallet_txs(request):
	"""
	POST: Pull new wallet-provider txns since timestamp; auto-mint credits
	"""
	if request.method != "POST":
		return HttpResponseBadRequest("POST only")
	body = json.loads(request.body or b"{}")
	since = body.get("since")
	result = DemoServices.ingest_since(since)
	return JsonResponse(result)


def mint(request):
	"""
	POST: Mint tokens for a specific provider_tx_id (credit) already ingested
	"""
	if request.method != "POST":
		return HttpResponseBadRequest("POST only")

	body = json.loads(request.body or b"{}")
	provider_tx_id = body.get("provider_tx_id")
	if not provider_tx_id:
		return HttpResponseBadRequest("provider_tx_id required")

	# Read idempotency key (optional)
	idempo = request.headers.get("Idempotency-Key")

	et = ExternalTransaction.objects.get(provider_tx_id=provider_tx_id)
	user = User.objects.get(email=settings.DEMO_USER_EMAIL)
	job = DemoServices.mint_from_provider_tx(user, et, idempotency_key=idempo)

	return JsonResponse({
		"job_id": str(job.id),
		"tx_hash": job.tx_hash,
		"amount_units": str(job.amount_units),
	}, status=201)


def redeem(request):
	"""
	POST: Burn tokens and debit wallet PKR equivalent (happy-path only)
	"""
	if request.method != "POST":
		return HttpResponseBadRequest("POST only")

	body = json.loads(request.body or b"{}")
	amount_units = body.get("amount_units")
	memo = body.get("memo", "cash-out")
	if not amount_units:
		return HttpResponseBadRequest("amount_units required")

	# Read idempotency key (optional)
	idempo = request.headers.get("Idempotency-Key")

	user = User.objects.get(email=settings.DEMO_USER_EMAIL)
	try:
		job = DemoServices.redeem(user, int(amount_units), memo, idempotency_key=idempo)
	except ValidationError as e:
		return JsonResponse({"error": e.message}, status=400)
		
	return JsonResponse({
		"job_id": str(job.id),
		"tx_hash": job.tx_hash,
		"amount_units": str(job.amount_units),
	}, status=201)