import os
import requests
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timedelta

def etree_to_dict(t):
    d = {t.tag: {} if t.attrib else None}
    children = list(t)
    if children:
        dd = {}
        for dc in map(etree_to_dict, children):
            for key, value in dc.items():
                if key in dd:
                    if not isinstance(dd[key], list):
                        dd[key] = [dd[key]]
                    dd[key].append(value)
                else:
                    dd[key] = value
        d = {t.tag: dd}
    if t.attrib:
        if t.tag not in d:
            d[t.tag] = {}
        if not isinstance(d[t.tag], dict):
            d[t.tag] = {}
        d[t.tag].update(('@' + k, v) for k, v in t.attrib.items())
    if t.text:
        text = t.text.strip()
        if children or t.attrib:
            if text:
                d[t.tag]['#text'] = text
        else:
            d[t.tag] = text
    return d

def get_train_data_plan(date_str, hour_str):
    url = f"https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1/plan/{os.getenv('DB_STATION')}/{date_str}/{hour_str}"
    headers = {
        "DB-Client-Id": os.getenv('DB_CLIENT_ID'),
        "DB-Api-Key": os.getenv('DB_CLIENT_SECRET'),
        "accept": "application/xml"
    }
    response = requests.get(url, headers=headers)
    root = ET.fromstring(response.text)
    data = etree_to_dict(root)
    return data

def get_train_data_fchg():
    # Fetch the fchg data for the station
    url = f"https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1/fchg/{os.getenv('DB_STATION')}"
    headers = {
        "DB-Client-Id": os.getenv('DB_CLIENT_ID'),
        "DB-Api-Key": os.getenv('DB_CLIENT_SECRET'),
        "accept": "application/xml"
    }
    response = requests.get(url, headers=headers)
    root = ET.fromstring(response.text)
    data = etree_to_dict(root)
    return data

def parse_time_code(time_code):
    # Time codes are in format YYMMDDHHMM
    # Example: "2412061230" = 2024-12-06 12:30
    if time_code and len(time_code) == 10:
        yy = time_code[0:2]
        mm = time_code[2:4]
        dd = time_code[4:6]
        hh = time_code[6:8]
        minu = time_code[8:10]
        year = "20" + yy
        return datetime.strptime(f"{year}-{mm}-{dd} {hh}:{minu}", "%Y-%m-%d %H:%M")
    return None

def to_str_time(time_code):
    dt = parse_time_code(time_code)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else None

now = datetime.now()
current_date_str = now.strftime("%y%m%d")
current_hour_str = now.strftime("%H")

next_hour = now + timedelta(hours=1)
next_date_str = next_hour.strftime("%y%m%d")
next_hour_str = next_hour.strftime("%H")

dates_hours = [(current_date_str, current_hour_str)]
if next_hour.date() != now.date():
    dates_hours.append((next_date_str, next_hour_str))
else:
    dates_hours.append((current_date_str, next_hour_str))

upper_limit = now + timedelta(minutes=int(os.getenv('KEEP_MINUTES')))

trains_info = []

# Fetch planned data
for date_str, hour_str in dates_hours:
    data = get_train_data_plan(date_str, hour_str)
    station_stops = data.get("timetable", {}).get("s", [])
    # Ensure station_stops is a list
    if isinstance(station_stops, dict):
        station_stops = [station_stops]

    for entry in station_stops:
        tl = entry.get("tl", {})
        dp = entry.get("dp", {})
        ar = entry.get("ar", {})

        # Extract trip data
        train_type = tl.get("@c")
        train_number = tl.get("@n")
        train_id = (tl.get("@c"), tl.get("@n"), tl.get("@f"), tl.get("@t"))

        # Planned times
        planned_departure_time_raw = dp.get("@pt")
        planned_arrival_time_raw = ar.get("@pt")

        planned_departure_str = to_str_time(planned_departure_time_raw)
        planned_arrival_str = to_str_time(planned_arrival_time_raw)

        route = dp.get("@ppth", "") or ar.get("@ppth", "")
        stations = route.split("|") if route else []
        destination = stations[-1] if stations else None

        planned_departure_platform = dp.get("@pp")
        planned_arrival_platform = ar.get("@pp")

        departure_datetime = parse_time_code(planned_departure_time_raw)

        # We only consider trains that depart within the defined time window
        if departure_datetime and now <= departure_datetime <= upper_limit:
            trains_info.append({
                "trip_id": train_id,
                "line": dp.get("@l") or ar.get("@l"),
                "train_type": train_type,
                "train_number": train_number,

                "destination": destination,

                # Planned times
                "planned_departure_raw": planned_departure_time_raw,
                "planned_departure_time": planned_departure_str,
                "planned_arrival_raw": planned_arrival_time_raw,
                "planned_arrival_time": planned_arrival_str,

                # Planned platforms
                "planned_departure_platform": planned_departure_platform,
                "planned_arrival_platform": planned_arrival_platform,

                # Actual times (to be filled from fchg)
                "actual_departure_raw": None,
                "actual_departure_time": None,
                "actual_arrival_raw": None,
                "actual_arrival_time": None,

                # Actual platforms
                "actual_departure_platform": None,
                "actual_arrival_platform": None,

                # Event statuses
                "departure_event_status": dp.get("@eStatus"),
                "arrival_event_status": ar.get("@eStatus"),

                # Delay source and delay info
                "delay_source": None,
                "delay_minutes": None,

                # Debug: store all found times from fchg
                "debug_dates": []
            })

# Fetch fchg data (actual changes)
fchg_data = get_train_data_fchg()
fchg_stations = fchg_data.get("timetable", {}).get("s", [])
if isinstance(fchg_stations, dict):
    fchg_stations = [fchg_stations]

for fchg_station in fchg_stations:
    tl = fchg_station.get("tl", {})
    ar = fchg_station.get("ar", {})
    dp = fchg_station.get("dp", {})

    fchg_trip_id = (tl.get("@c"), tl.get("@n"), tl.get("@f"), tl.get("@t"))

    # Extract actual times
    actual_departure_raw = dp.get("@ct")
    actual_arrival_raw = ar.get("@ct")

    actual_departure_str = to_str_time(actual_departure_raw)
    actual_arrival_str = to_str_time(actual_arrival_raw)

    # Actual platforms
    actual_departure_platform = dp.get("@cp")
    actual_arrival_platform = ar.get("@cp")

    # Delay source
    delay_source = dp.get("@ds") or ar.get("@ds")

    # Append debug info and update train in trains_info if trip_id matches
    for train in trains_info:
        if train["trip_id"] == fchg_trip_id:
            found_dates = {}
            if actual_arrival_raw:
                found_dates["ar_ct"] = actual_arrival_raw
            if actual_departure_raw:
                found_dates["dp_ct"] = actual_departure_raw

            if found_dates:
                train["debug_dates"].append(found_dates)

            # Update actual times
            if actual_departure_raw:
                train["actual_departure_raw"] = actual_departure_raw
                train["actual_departure_time"] = actual_departure_str
            if actual_arrival_raw:
                train["actual_arrival_raw"] = actual_arrival_raw
                train["actual_arrival_time"] = actual_arrival_str

            # Update actual platforms
            if actual_departure_platform:
                train["actual_departure_platform"] = actual_departure_platform
            if actual_arrival_platform:
                train["actual_arrival_platform"] = actual_arrival_platform

            # Update event statuses
            if dp.get("@eStatus"):
                train["departure_event_status"] = dp.get("@eStatus")
            if ar.get("@eStatus"):
                train["arrival_event_status"] = ar.get("@eStatus")

            # Update delay source
            if delay_source:
                train["delay_source"] = delay_source

            # Compute delay if both planned and actual departure times are known
            planned_dt = parse_time_code(train["planned_departure_raw"])
            actual_dt = parse_time_code(train["actual_departure_raw"])
            if planned_dt and actual_dt:
                delay_delta = actual_dt - planned_dt
                delay_minutes = int(delay_delta.total_seconds() // 60)
                train["delay_minutes"] = delay_minutes

# Sort by planned departure time (string conversion safe)
trains_info_sorted = sorted(trains_info, key=lambda x: x["planned_departure_time"] or "")

print(json.dumps(trains_info_sorted, indent=4, ensure_ascii=False))
