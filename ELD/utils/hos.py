from datetime import datetime, timedelta
import math

# Constants
MAX_DRIVING_HOURS = 11.0
MAX_WINDOW_HOURS = 14.0
REQUIRED_BREAK_MIN = 30
ROLLING_LIMIT_HOURS = 70.0  # for 70/8 rule; could be configurable
SLEEPER_RESTART_HOURS = 34.0

def estimate_drive_time_and_distance(osrm_route):
    # osrm_route: expected dict with distance (meters) and duration (seconds)
    miles = osrm_route['distance'] * 0.000621371
    minutes = osrm_route['duration'] / 60.0
    return miles, minutes

def split_into_daily_logs(start_dt: datetime, total_drive_minutes: float, cycle_hours_used: float):
    """
    Simple greedy split:
    - simulate a continuous trip starting at start_dt
    - allocate driving blocks up to MAX_DRIVING_HOURS (in minutes), enforce 30-min break after 8 driving hours
    - ensure no driving after 14-hour window (we will model on-duty window) — for MVP we produce logs by 24-hr day
    Returns list of days: [{date, entries:[{status, start, end, minutes, location}], totals: {...}}]
    """
    remaining_minutes = total_drive_minutes
    current = start_dt
    logs = []
    # For MVP assume average speed and fixed locations; we only produce duty blocks for driving and breaks
    while remaining_minutes > 0:
        day_start = datetime(current.year, current.month, current.day, 0, 0, 0)
        day_end = day_start + timedelta(days=1)
        day = {'date': day_start.date().isoformat(), 'entries': [], 'totals': {'driving': 0, 'on_duty_not_driving': 0, 'off_duty': 0, 'sleeper': 0}}
        # simple: allow up to MAX_DRIVING_HOURS per day (11h) and 14h window in which driving must occur
        daily_driving_remaining = min(MAX_DRIVING_HOURS * 60, remaining_minutes)
        # simulate driving in chunks, inserting 30-min break after 8 driving hours cumulative
        driven_this_day = 0
        while daily_driving_remaining > 0:
            # how much until 8 hours cumulative since last break? For MVP we track within-day only
            chunk = min(daily_driving_remaining, (MAX_DRIVING_HOURS*60 - driven_this_day))
            # enforce 30-min break if we pass 8 hours (480 min) cumulative
            if driven_this_day + chunk > 480:
                before = 480 - driven_this_day
                if before > 0:
                    day['entries'].append({'status':'driving','start':current.isoformat(),'end':(current + timedelta(minutes=before)).isoformat(),'minutes': before})
                    current += timedelta(minutes=before)
                    remaining_minutes -= before
                    daily_driving_remaining -= before
                    driven_this_day += before
                # add 30-min break
                day['entries'].append({'status':'break','start':current.isoformat(),'end':(current + timedelta(minutes=REQUIRED_BREAK_MIN)).isoformat(),'minutes': REQUIRED_BREAK_MIN})
                current += timedelta(minutes=REQUIRED_BREAK_MIN)
                day['totals']['on_duty_not_driving'] += REQUIRED_BREAK_MIN
                continue
            # otherwise drive chunk
            day['entries'].append({'status':'driving','start':current.isoformat(),'end':(current + timedelta(minutes=chunk)).isoformat(),'minutes': chunk})
            current += timedelta(minutes=chunk)
            remaining_minutes -= chunk
            daily_driving_remaining -= chunk
            driven_this_day += chunk
            day['totals']['driving'] += chunk
            # if still driving allowed in day and remaining > 0, we may insert a short on-duty stop of 30 min (pickup/drop)
            if remaining_minutes > 0 and driven_this_day >= MAX_DRIVING_HOURS*60:
                # reached daily driving cap
                break
        logs.append(day)
        # move to next day beginning if still remaining
        if remaining_minutes > 0:
            # assume 10 hours off required before next driving window — for MVP we simulate off-duty overnight
            off_minutes = 600  # 10 hours off
            day['entries'].append({'status':'off_duty','start':current.isoformat(),'end':(current+timedelta(minutes=off_minutes)).isoformat(),'minutes': off_minutes})
            day['totals']['off_duty'] += off_minutes
            current += timedelta(minutes=off_minutes)
        else:
            # finished
            break
    return logs
