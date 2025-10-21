"""URL routing for API + local stubs (wallet + chain).


The /api/ namespace exposes demo operations; /stub/* exposes deterministic stubs
used by adapters. In production, stubs are replaced by real providers.
"""

from django.contrib import admin
from django.urls import path, include


urlpatterns = [
	path("admin/", admin.site.urls),
	path("api/", include("api.urls")),
	path("stub/wallet/", include("wallet_stub.urls")),
	path("stub/chain/", include("chain_stub.urls")),
]