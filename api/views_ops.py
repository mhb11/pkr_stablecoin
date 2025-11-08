"""Operational endpoints that move the system forward (ingest/mint/redeem)."""

import hmac, json, hashlib, ipaddress
from decimal import Decimal
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.core.exceptions import ValidationError
from django.conf import settings
from django.middleware.csrf import get_token
from core.services import DemoServices, perform_mint_for_external_tx, process_payout_for_onchain_event
from core.models import ExternalTransaction, ExternalTransactionStatus, OnchainEvent, User, WalletAccount


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


# --- Helpers -----------------------------------------------------------------

def _hmac_valid(raw_body: bytes, provided_sig: str, secret: str) -> bool:
	mac = hmac.new(key=secret.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256)
	expected = mac.hexdigest()
	try:
		return hmac.compare_digest(expected, provided_sig)
	except Exception:
		return False

def _ip_allowed(request) -> bool:
	allowed = getattr(settings, "BANK_WEBHOOK_IP_ALLOWLIST", [])
	if not allowed:
		return True
	try:
		src = ipaddress.ip_address(request.META.get("REMOTE_ADDR", "127.0.0.1"))
		return any(src in ipaddress.ip_network(net) for net in allowed)
	except ValueError:
		return False


def _resolve_user_from_bank_payload(payload: dict) -> User:
	"""
	Prefer stable identifiers in this order:
	1) metadata.user_uuid  (UUID primary key of core.User)
	2) metadata.user_email (email of the demo user)
	3) memo="user:<uuid>"  (UUID in memo)
	4) fallback to DEMO_USER_EMAIL (dev convenience)
	"""
	meta = payload.get("metadata") or {}

	if "user_uuid" in meta:
		return User.objects.get(id=meta["user_uuid"])

	if "user_email" in meta:
		return User.objects.get(email=str(meta["user_email"]).strip().lower())

	memo = (payload.get("memo") or "").strip()
	if memo.lower().startswith("user:"):
		uid = memo.split(":", 1)[1].strip()
		return User.objects.get(id=uid)

	# Dev-only fallback: demo user
	return User.objects.get(email=settings.DEMO_USER_EMAIL)


def _parse_chainhook_burns(payload: dict):
	"""
	Extract a list of burn events with (txid, event_index, user_address, amount_units, asset_identifier).

	For MVP we support a simple format *or* a Chainhook-like shape:
	- Simple:
	  {"events":[{"type":"burn","txid":"...","event_index":0,"user_address":"ST...","amount_units":12345,"asset":"SP..token::pkr"}]}
	- Chainhook-ish:
	  {"transactions":[{"transaction_hash":"...","events":[
		  {"event_index":0,"event_type":"fungible_token_burn","asset_identifier":"SP..::pkr","sender":"ST...","amount":"12345"}
	  ]}]}
	Adjust mapping to your emitted Clarity event exactly.
	"""
	out = []

	# Simple
	if "events" in payload and isinstance(payload["events"], list):
		for e in payload["events"]:
			if (e.get("type") == "burn") and "amount_units" in e:
				out.append(dict(
					txid=e["txid"],
					event_index=int(e["event_index"]),
					user_address=e["user_address"],
					amount_units=int(e["amount_units"]),
					asset_identifier=e.get("asset", ""),
				))
		return out

	# Chainhook-ish
	for tx in payload.get("transactions", []):
		txid = tx.get("transaction_hash")
		for ev in tx.get("events", []):
			et = ev.get("event_type")
			if et in ("fungible_token_burn", "ft_burn", "contract_event"):  # be flexible
				# Try common keys
				amount = ev.get("amount") or ev.get("value") or ev.get("raw_value")
				sender = ev.get("sender") or ev.get("principal") or ev.get("owner")
				asset = ev.get("asset_identifier") or ""
				if amount is None or sender is None:
					continue
				try:
					amt_units = int(str(amount))
				except Exception:
					continue
				out.append(dict(
					txid=txid,
					event_index=int(ev.get("event_index", 0)),
					user_address=str(sender),
					amount_units=amt_units,
					asset_identifier=asset,
				))
	return out

def _resolve_user_from_stacks_address(addr: str) -> User:
	"""
	MVP strategy:
	- If the "address" looks like an email, resolve by email.
	- Otherwise, fall back to the demo user (until we add a proper mapping table).
	"""
	if "@" in addr:
		return User.objects.get(email=addr.strip().lower())
	return User.objects.get(email=settings.DEMO_USER_EMAIL)
	

# --- Webhooks ----------------------------------------------------------------

@csrf_exempt
def bank_webhook(request):
	"""
	Validates HMAC + optional IP allowlist.
	Body format (example):
	{
	  "provider_tx_id": "bank123",
	  "direction": "credit",         // or "debit"
	  "amount_pkr": "20000.00",
	  "status": "settled",
	  "occurred_at": "2025-11-08T00:58:00Z",    // optional; defaults to now()
	  "memo": "user:<uuid>"                     // optional
	  "metadata": {"user_uuid": "<uuid>", "user_email": "demo@example.com"} // any one is fine
	}
	"""
	if request.method != "POST":
		return HttpResponseBadRequest("POST required")

	if not _ip_allowed(request):
		return HttpResponseForbidden("IP not allowed")

	secret = getattr(settings, "BANK_WEBHOOK_SECRET", None)
	signature = request.headers.get("X-Signature") or ""
	raw = request.body or b""
	try:
		payload = json.loads(raw.decode("utf-8"))
	except Exception:
		return HttpResponseBadRequest("Invalid JSON")

	if not secret or not _hmac_valid(raw, signature, secret):
		return HttpResponseForbidden("Bad signature")

	try:
		provider_tx_id = str(payload["provider_tx_id"])
		direction = str(payload.get("direction", "")).lower()
		status = str(payload.get("status", "")).lower()
		amount_pkr = Decimal(str(payload["amount_pkr"]))

		# Figure out occurred_at (optional in payload)
		occurred_at_str = payload.get("occurred_at") or payload.get("created_at")
		occurred_at = parse_datetime(occurred_at_str) if occurred_at_str else None
		if occurred_at is None:
			occurred_at = timezone.now()
		elif occurred_at.tzinfo is None:
			# Make it timezone-aware if provider sent naive
			occurred_at = occurred_at.replace(tzinfo=timezone.utc)

		# Resolve user and wallet account
		user = _resolve_user_from_bank_payload(payload)
		try:
			wa = WalletAccount.objects.get(user=user)
		except WalletAccount.DoesNotExist:
			wa = WalletAccount.objects.create(user=user, provider="stub-wallet", provider_acct="WALLET-001")

		# For non-credit / non-settled / non-positive amounts: store ET as IGNORED so we still have a row
		if direction != "credit" or status != "settled" or amount_pkr <= 0:
			with transaction.atomic():
				ExternalTransaction.objects.get_or_create(
					provider_tx_id=provider_tx_id,
					defaults=dict(
						wallet_acct=wa,
						amount_pkr=amount_pkr,
						direction=direction,
						memo=payload.get("memo", ""),
						occurred_at=occurred_at,
						status=ExternalTransactionStatus.IGNORED,
					),
				)
			return JsonResponse({"ok": True, "ignored": True})

		# CREDIT + SETTLED + amount > 0 → create ET(RECEIVED) then mint
		with transaction.atomic():
			et, created = ExternalTransaction.objects.get_or_create(
				provider_tx_id=provider_tx_id,
				defaults=dict(
					wallet_acct=wa,
					amount_pkr=amount_pkr,
					direction=direction,
					memo=payload.get("memo", ""),
					occurred_at=occurred_at,
					status=ExternalTransactionStatus.RECEIVED,
				),
			)

			if et.status == ExternalTransactionStatus.MINTED:
				return JsonResponse({"ok": True, "idempotent": True, "status": et.status})

			# Mint now; idempotency_key ties back to bank tx id
			tx_hash = perform_mint_for_external_tx(
				external_tx=et,
				user=user,
				idempotency_key=f"bank:{provider_tx_id}",
			)

		return JsonResponse({"ok": True, "minted": True, "tx_hash": tx_hash})

	except User.DoesNotExist:
		return HttpResponseBadRequest("Unknown user")
	except KeyError as e:
		return HttpResponseBadRequest(f"Missing field: {e}")
	except Exception:
		# Don’t leak internals; log exception server-side
		return HttpResponseBadRequest("Webhook processing error")



@csrf_exempt
def stacks_chainhook_webhook(request):
	"""
	Accepts Chainhook (or simple) payloads, records burn events idempotently,
	and creates payout jobs (attempts payout immediately in MVP).
	"""
	if request.method != "POST":
		return HttpResponseBadRequest("POST required")

	try:
		payload = json.loads((request.body or b"{}").decode("utf-8"))
	except Exception:
		return HttpResponseBadRequest("Invalid JSON")

	burns = _parse_chainhook_burns(payload)
	if not burns:
		return JsonResponse({"ok": True, "events": 0})

	processed = 0
	for e in burns:
		try:
			user = _resolve_user_from_stacks_address(e["user_address"])
			with transaction.atomic():
				ev, created = OnchainEvent.objects.get_or_create(
					txid=e["txid"],
					event_index=e["event_index"],
					defaults=dict(
						chain="stacks-testnet",
						event_type="burn",
						user=user,
						amount_units=int(e["amount_units"]),
						asset_identifier=e.get("asset_identifier", ""),
					),
				)
				if not created:
					# Already seen (idempotent)
					continue

				# Kick payout (MVP: sync)
				process_payout_for_onchain_event(ev)

			processed += 1

		except User.DoesNotExist:
			# Skip unknown address; you can log and alert.
			continue
		except Exception:
			# Log and continue; we don't want to fail the whole batch
			continue

	return JsonResponse({"ok": True, "events": processed})