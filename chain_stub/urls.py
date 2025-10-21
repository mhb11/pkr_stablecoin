from django.urls import path
from .views import get_balance, mint, burn


urlpatterns = [
	path("balance/<uuid:user_id>", get_balance),
	path("mint", mint),
	path("burn", burn),
]