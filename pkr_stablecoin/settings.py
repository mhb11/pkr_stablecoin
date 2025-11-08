"""Django settings for the PKR stablecoin MVP demo.


This project runs a minimal, happy-path flow:
- Simulated wallet deposits (wallet_stub) → mint tokens (chain_stub)
- Burn tokens → simulated wallet debit


Security, auth, retries, and idempotency are intentionally omitted for clarity.
"""

import os
from pathlib import Path
from decimal import Decimal


BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.getenv("DEBUG", "1") in ("1", "true", "True", "yes")
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if os.getenv("CSRF_TRUSTED_ORIGINS") else []

def env_bool(name, default=""):
    v = os.getenv(name, default)
    return v.lower() in ("1", "true", "yes", "on")

#######################
# HMAC secret for the bank webhook (set in env)
BANK_WEBHOOK_SECRET = os.getenv("BANK_WEBHOOK_SECRET", "dev-secret-change-me")

# Optional IP allowlist for bank webhook (CIDRs). Empty => allow all (dev).
BANK_WEBHOOK_IP_ALLOWLIST = [
    # "203.0.113.0/24",
    # "198.51.100.10/32",
]

# Optional ceilings
# from decimal import Decimal
MAX_SINGLE_MINT_PKR = Decimal("5000000.00")
MAX_SINGLE_PAYOUT_PKR = Decimal("5000000.00")
#######################


INSTALLED_APPS = [
	"django.contrib.admin",
	"django.contrib.auth",
	"django.contrib.contenttypes",
	"django.contrib.sessions",
	"django.contrib.messages",
	"django.contrib.staticfiles",
	# local apps
	"core",
	"api",
	"wallet_stub",
	"chain_stub",
]


MIDDLEWARE = [
	"django.middleware.security.SecurityMiddleware",
	"django.contrib.sessions.middleware.SessionMiddleware",
	"django.middleware.common.CommonMiddleware",
	"django.middleware.csrf.CsrfViewMiddleware",
	"django.contrib.auth.middleware.AuthenticationMiddleware",
	"django.contrib.messages.middleware.MessageMiddleware",
]


ROOT_URLCONF = "pkr_stablecoin.urls"
TEMPLATES = [
	{
		"BACKEND": "django.template.backends.django.DjangoTemplates",
		"DIRS": [],
		"APP_DIRS": True,
		"OPTIONS": {
			"context_processors": [
				"django.template.context_processors.debug",
				"django.template.context_processors.request",
				"django.contrib.auth.context_processors.auth",
				"django.contrib.messages.context_processors.messages",
			],
		},
	},
]


WSGI_APPLICATION = "pkr_stablecoin.wsgi.application"


DB_ENGINE = os.getenv("DB_ENGINE", "sqlite")
if DB_ENGINE == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "pkr_demo"),
            "USER": os.getenv("POSTGRES_USER", "pkr_demo"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", "pkr_demo"),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }



AUTH_PASSWORD_VALIDATORS = []


LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Demo-wide constants: token uses 6 decimals; a single demo user is seeded.
TOKEN_DECIMALS = 6
DEMO_USER_EMAIL = "hassan@bitcoinl2labs.com"