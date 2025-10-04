from django.db import models # type: ignore
class Driver(models.Model):
    name = models.CharField(max_length=200)
    driver_number = models.CharField(max_length=50, blank=True, null=True)

class Trip(models.Model):
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE)
    start_datetime = models.DateTimeField()
    current_location = models.CharField(max_length=255)
    pickup_location = models.CharField(max_length=255)
    dropoff_location = models.CharField(max_length=255)
    cycle_hours_used = models.FloatField(help_text="Hours already used in current cycle (e.g., 32.5)")
    full_geometry = models.JSONField(null=True, blank=True)  # GeoJSON LineString
    created_at = models.DateTimeField(auto_now_add=True)
    result = models.JSONField(null=True, blank=True)  # stores computed route + logs
