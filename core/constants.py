"""Unit conversion helpers shared across the demo.


- TOKEN_DECIMALS controls the token granularity.
- pkr_to_units / units_to_pkr convert between human PKR and integer token units.
"""

from django.conf import settings


TOKEN_DECIMALS = getattr(settings, "TOKEN_DECIMALS", 6)
FACTOR = 10 ** TOKEN_DECIMALS


def pkr_to_units(pkr_str: str | float):
	"""
	Convert human-readable PKR string (e.g., "1000.00") to integer token units using TOKEN_DECIMALS
	"""
	return int(round(float(pkr_str) * FACTOR))


def units_to_pkr(units: int) -> float:
	"""
	Convert integer token units back to human-readable PKR string for wallet debits/displays.
	"""
	return units / FACTOR