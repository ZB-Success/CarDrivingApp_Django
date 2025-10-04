from django.urls import path
from .views import TripView

urlpatterns = [
    path('trip/', TripView.as_view(), name='trip-create'),
]
