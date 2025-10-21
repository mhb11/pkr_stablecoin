from django.urls import path
from .views import balance, transactions, credit, debit


urlpatterns = [
	path("balance", balance),
	path("transactions", transactions),
	path("credit", credit),
	path("debit", debit),
]