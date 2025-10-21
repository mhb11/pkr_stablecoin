"""In-process chain balance table to simulate confirmed on-chain state per user"""

import uuid
from django.db import models


class ChainStubBalance(models.Model):
	"""
	Tracks per-user token balance as if confirmed on-chain
	"""
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	user_id = models.UUIDField(unique=True)
	balance_units = models.BigIntegerField(default=0)