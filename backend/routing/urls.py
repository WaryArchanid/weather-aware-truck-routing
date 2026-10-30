from django.urls import path
from .views import health, analyze_trip

urlpatterns = [
    path('health/', health, name='health'),
    path(
        "routes/analyze/",
        analyze_trip,
        name="analyze-trip"
    ),
]