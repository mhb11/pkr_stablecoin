"""Unit conversion helpers shared across the demo.


- TOKEN_DECIMALS controls the token granularity.
- pkr_to_units / units_to_pkr convert between human PKR and integer token units.
"""

from django.conf import settings
from decimal import Decimal, ROUND_DOWN

TOKEN_DECIMALS = getattr(settings, "TOKEN_DECIMALS", 6)
TEN_POW = 10 ** TOKEN_DECIMALS


def pkr_to_units(amount_pkr: str | Decimal) -> int:
    """
    Convert human-readable PKR string (e.g., "1000.00") to integer token units using TOKEN_DECIMALS
    """
    amount_pkr = Decimal(amount_pkr)  # accept str or Decimal
    return int((amount_pkr * Decimal(TEN_POW)).quantize(Decimal("1"), rounding=ROUND_DOWN))


def units_to_pkr(amount_units: int) -> Decimal:
    """
    Convert integer token units back to a 2-decimal PKR amount.
    """
    return (Decimal(amount_units) / Decimal(TEN_POW)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
