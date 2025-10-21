"""Django settings for the PKR stablecoin MVP demo.


This project runs a minimal, happy-path flow:
- Simulated wallet deposits (wallet_stub) → mint tokens (chain_stub)
- Burn tokens → simulated wallet debit


Security, auth, retries, and idempotency are intentionally omitted for clarity.
"""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "dev-key-not-for-prod"
DEBUG = True
ALLOWED_HOSTS = ["*"]


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