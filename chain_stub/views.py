"""HTTP endpoints for the chain stub mirroring a mint/burn RPC surface"""

import json
from django.http import JsonResponse, HttpResponseBadRequest
from .models import ChainStubBalance


def get_balance(request, user_id: str):
	"""
	GET: Return the simulated on-chain balance for a user id
	"""
	obj, _ = ChainStubBalance.objects.get_or_create(user_id=user_id, defaults={"balance_units": 0})
	return JsonResponse({"balance_units": str(obj.balance_units)})


def mint(request):
	"""
	POST: Increment the user's chain balance; return a confirmed tx receipt
	"""
	if request.method != "POST":
		return HttpResponseBadRequest("POST only")
	body = json.loads(request.body or b"{}")
	user_id = body.get("to_user_id")
	amount_units = int(body.get("amount_units", 0))
	obj, _ = ChainStubBalance.objects.get_or_create(user_id=user_id, defaults={"balance_units": 0})
	obj.balance_units += amount_units
	obj.save(update_fields=["balance_units"])
	return JsonResponse({"tx_hash": "0xM1", "status": "confirmed"}, status=201)


def burn(request):
	"""
	POST: Decrement the user's chain balance; return a confirmed tx receipt
	"""
	if request.method != "POST":
		return HttpResponseBadRequest("POST only")
	body = json.loads(request.body or b"{}")
	user_id = body.get("from_user_id")
	amount_units = int(body.get("amount_units", 0))
	obj, _ = ChainStubBalance.objects.get_or_create(user_id=user_id, defaults={"balance_units": 0})
	obj.balance_units -= amount_units
	obj.save(update_fields=["balance_units"])
	return JsonResponse({"tx_hash": "0xB1", "status": "confirmed"}, status=201)