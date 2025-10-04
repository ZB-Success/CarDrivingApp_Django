
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Trip
import requests
from datetime import datetime, timedelta
from .utils.geo import geocode_address

OSRM_BASE = 'http://router.project-osrm.org/route/v1/driving/'

# -----------------------------
# Helper Conversions
# -----------------------------
def meters_to_miles(m):
    return m / 1609.34

def seconds_to_minutes(s):
    return s / 60

# -----------------------------
# Call OSRM API
# -----------------------------
def call_osrm_route(origin, dest):
    """
    origin/dest expected as "lon,lat" strings.
    Returns miles, minutes, and geometry.
    """
    url = f"{OSRM_BASE}{origin};{dest}?overview=full&geometries=geojson"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    route = data['routes'][0]
    return {
        'distance_miles': meters_to_miles(route['distance']),
        'duration_min': seconds_to_minutes(route['duration']),
        'geometry': route['geometry']
    }

# -----------------------------
# FMCSA Hours-of-Service Logic
# -----------------------------
def split_into_daily_logs(start_dt, total_minutes, cycle_hours_used):
    """
    Generate daily logs applying FMCSA rules:
    - Max 11 hours driving in 14-hour window
    - 30-min break after 8 hours driving
    - 70-hour/8-day cycle
    """
    logs = []
    remaining = total_minutes
    day_cursor = start_dt
    cycle_used = cycle_hours_used

    # Keep generating logs until trip minutes are consumed
    while remaining > 0:
        day_log = {
            "date": day_cursor.strftime("%Y-%m-%d"),
            "entries": [],
            "totals": {"driving": 0, "on_duty_not_driving": 0, "off_duty": 0, "sleeper": 0}
        }

        # Allow up to 11 driving hours (660 minutes) in one day
        drive_limit = min(remaining, 660)

        # Add mandatory 30-min break if > 480 mins
        if drive_limit > 480:
            drive_session = 480
            break_time = 30
            second_drive = min(drive_limit - drive_session - break_time, 180)  # up to 3 hrs left
            total_today = drive_session + break_time + second_drive

            # Driving before break
            day_log["entries"].append({
                "status": "driving",
                "start": day_cursor.isoformat(),
                "end": (day_cursor + timedelta(minutes=drive_session)).isoformat(),
                "minutes": drive_session
            })

            # 30-min break (off duty)
            break_start = day_cursor + timedelta(minutes=drive_session)
            day_log["entries"].append({
                "status": "off_duty",
                "start": break_start.isoformat(),
                "end": (break_start + timedelta(minutes=30)).isoformat(),
                "minutes": break_time
            })

            # Driving after break
            drive2_start = break_start + timedelta(minutes=30)
            day_log["entries"].append({
                "status": "driving",
                "start": drive2_start.isoformat(),
                "end": (drive2_start + timedelta(minutes=second_drive)).isoformat(),
                "minutes": second_drive
            })

            day_log["totals"]["driving"] = drive_session + second_drive
            day_log["totals"]["off_duty"] = break_time
            used_today = total_today

        else:
            # All driving in one block
            day_log["entries"].append({
                "status": "driving",
                "start": day_cursor.isoformat(),
                "end": (day_cursor + timedelta(minutes=drive_limit)).isoformat(),
                "minutes": drive_limit
            })
            day_log["totals"]["driving"] = drive_limit
            used_today = drive_limit

        logs.append(day_log)
        remaining -= used_today
        cycle_used += used_today / 60  # add driving hours to cycle
        day_cursor += timedelta(days=1)  # move to next day

        # FMCSA cycle reset rule (simplified): if cycle exceeds 70 hrs → force 34 hr off duty
        if cycle_used >= 70:
            reset_entry = {
                "date": day_cursor.strftime("%Y-%m-%d"),
                "entries": [{
                    "status": "off_duty",
                    "start": day_cursor.isoformat(),
                    "end": (day_cursor + timedelta(hours=34)).isoformat(),
                    "minutes": 34 * 60
                }],
                "totals": {"driving": 0, "on_duty_not_driving": 0, "off_duty": 34*60, "sleeper": 0}
            }
            logs.append(reset_entry)
            cycle_used = 0
            day_cursor += timedelta(hours=34)

    return logs

# -----------------------------
# API View
# -----------------------------
class TripView(APIView):
    def get(self, request):
        trips = Trip.objects.all()
        if not trips:
            return Response("No trips found.", content_type="text/plain", status=status.HTTP_200_OK)

        response_text = ""
        for trip in trips:
            response_text += (
                f"Trip ID: {trip.id}\n"
                f"Driver: {trip.driver_id}\n"
                f"Start: {trip.start_datetime}\n"
                f"From: {trip.current_location}\n"
                f"Pickup: {trip.pickup_location}\n"
                f"Dropoff: {trip.dropoff_location}\n"
                f"Distance/Duration: {trip.result.get('route', {}).get('distance_miles','')} miles / {trip.result.get('route', {}).get('duration_min','')} min\n"
                "-------------------------\n"
            )
        return Response(response_text, content_type="text/plain", status=status.HTTP_200_OK)
    def post(self, request):
        data = request.data
        start_dt = datetime.fromisoformat(data.get('start_datetime'))
        cycle_hours_used = float(data.get('cycle_hours_used', 0))

        origin = geocode_address(data.get('current_location'))   # "lon,lat"
        pickup = geocode_address(data.get('pickup_location'))
        dropoff = geocode_address(data.get('dropoff_location'))

        # Step 1: Route segments
        r1 = call_osrm_route(origin, pickup)
        r2 = call_osrm_route(pickup, dropoff)

        # Step 2: Total miles + minutes
        total_distance = r1['distance_miles'] + r2['distance_miles']
        total_duration = r1['duration_min'] + r2['duration_min']

        # Step 3: HOS logs
        logs = split_into_daily_logs(start_dt, total_duration, cycle_hours_used)

        # Step 4: Save trip in DB
        full_geometry = {
            "type": "LineString",
            "coordinates": r1['geometry']['coordinates'] + r2['geometry']['coordinates']
        }
        trip = Trip.objects.create(
            driver_id=data.get('driver'),
            start_datetime=start_dt,
            current_location=data.get('current_location',''),
            pickup_location=data.get('pickup_location',''),
            dropoff_location=data.get('dropoff_location',''),
            cycle_hours_used=cycle_hours_used,
            full_geometry = full_geometry,     
            result={
                'route': {
                    'distance_miles': total_distance,
                    'duration_min': total_duration,
                    'geometry': full_geometry  # ✅ Now geometry goes to frontend
                },
                'logs': logs
            }
        )

        # Step 5: Respond
        return Response(trip.result, status=status.HTTP_201_CREATED)
    def get(self, request):
        return Response("Hello! Backend is working fine.", content_type="text/plain")
