from django.urls import path # type: ignore
from .views import TripView

urlpatterns = [
    path('trip/', TripView.as_view(), name='trip-create'),
    path("getLists/", TripView.as_view(), name="trip-list"),
]
