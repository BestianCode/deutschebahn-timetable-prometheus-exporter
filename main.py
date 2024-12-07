import os
import requests
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timedelta
import threading
import time
from flask import Flask, Response, jsonify

app = Flask(__name__)

latest_trains_info = []

UPDATE_INTERVAL = 60

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
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        data = etree_to_dict(root)
        return data
    except requests.RequestException as e:
        print(f"Error fetching plan data: {e}")
        return {}
    except ET.ParseError as e:
        print(f"Error parsing plan XML: {e}")
        return {}

def get_train_data_fchg():
    url = f"https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1/fchg/{os.getenv('DB_STATION')}"
    headers = {
        "DB-Client-Id": os.getenv('DB_CLIENT_ID'),
        "DB-Api-Key": os.getenv('DB_CLIENT_SECRET'),
        "accept": "application/xml"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        data = etree_to_dict(root)
        return data
    except requests.RequestException as e:
        print(f"Error fetching fchg data: {e}")
        return {}
    except ET.ParseError as e:
        print(f"Error parsing fchg XML: {e}")
        return {}

def parse_time_code(time_code):
    if time_code and len(time_code) == 10:
        try:
            yy = time_code[0:2]
            mm = time_code[2:4]
            dd = time_code[4:6]
            hh = time_code[6:8]
            minu = time_code[8:10]
            year = "20" + yy
            return datetime.strptime(f"{year}-{mm}-{dd} {hh}:{minu}", "%Y-%m-%d %H:%M")
        except ValueError as e:
            print(f"Error parsing time code {time_code}: {e}")
            return None
    return None

def to_str_time(time_code):
    dt = parse_time_code(time_code)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else None

def fetch_and_update_data():
    global latest_trains_info
    while True:
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

        upper_limit = now + timedelta(minutes=int(os.getenv('KEEP_MINUTES', '60')))

        trains_info = []

        for date_str, hour_str in dates_hours:
            data = get_train_data_plan(date_str, hour_str)
            station_stops = data.get("timetable", {}).get("s", [])
            if isinstance(station_stops, dict):
                station_stops = [station_stops]

            for entry in station_stops:
                tl = entry.get("tl", {})
                dp = entry.get("dp", {})
                ar = entry.get("ar", {})

                train_type = tl.get("@c")
                train_number = tl.get("@n")
                trip_id = f"{tl.get('@c')}_{tl.get('@n')}_{tl.get('@f', '')}_{tl.get('@t', '')}"

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

                if departure_datetime and now <= departure_datetime <= upper_limit:
                    trains_info.append({
                        "trip_id": trip_id,
                        "line": dp.get("@l") or ar.get("@l"),
                        "train_type": train_type,
                        "train_number": train_number,
                        "destination": destination,

                        "planned_departure_raw": planned_departure_time_raw,
                        "planned_departure_time": planned_departure_str,
                        "planned_arrival_raw": planned_arrival_time_raw,
                        "planned_arrival_time": planned_arrival_str,

                        "planned_departure_platform": planned_departure_platform,
                        "planned_arrival_platform": planned_arrival_platform,

                        "actual_departure_raw": None,
                        "actual_departure_time": None,
                        "actual_arrival_raw": None,
                        "actual_arrival_time": None,

                        "actual_departure_platform": None,
                        "actual_arrival_platform": None,

                        "departure_event_status": dp.get("@eStatus"),
                        "arrival_event_status": ar.get("@eStatus"),

                        "delay_source": None,
                        "delay_minutes": None,

                        "debug_dates": []
                    })

        fchg_data = get_train_data_fchg()
        fchg_stations = fchg_data.get("timetable", {}).get("s", [])
        if isinstance(fchg_stations, dict):
            fchg_stations = [fchg_stations]

        for fchg_station in fchg_stations:
            tl = fchg_station.get("tl", {})
            ar = fchg_station.get("ar", {})
            dp = fchg_station.get("dp", {})

            fchg_trip_id = f"{tl.get('@c')}_{tl.get('@n')}_{tl.get('@f', '')}_{tl.get('@t', '')}"

            actual_departure_raw = dp.get("@ct")
            actual_arrival_raw = ar.get("@ct")

            actual_departure_str = to_str_time(actual_departure_raw)
            actual_arrival_str = to_str_time(actual_arrival_raw)

            actual_departure_platform = dp.get("@cp")
            actual_arrival_platform = ar.get("@cp")

            delay_source = dp.get("@ds") or ar.get("@ds")

            for train in trains_info:
                if train["trip_id"] == fchg_trip_id:
                    found_dates = {}
                    if actual_arrival_raw:
                        found_dates["ar_ct"] = actual_arrival_raw
                    if actual_departure_raw:
                        found_dates["dp_ct"] = actual_departure_raw

                    if found_dates:
                        train["debug_dates"].append(found_dates)

                    if actual_departure_raw:
                        train["actual_departure_raw"] = actual_departure_raw
                        train["actual_departure_time"] = actual_departure_str
                    if actual_arrival_raw:
                        train["actual_arrival_raw"] = actual_arrival_raw
                        train["actual_arrival_time"] = actual_arrival_str

                    if actual_departure_platform:
                        train["actual_departure_platform"] = actual_departure_platform
                    if actual_arrival_platform:
                        train["actual_arrival_platform"] = actual_arrival_platform

                    if dp.get("@eStatus"):
                        train["departure_event_status"] = dp.get("@eStatus")
                    if ar.get("@eStatus"):
                        train["arrival_event_status"] = ar.get("@eStatus")

                    if delay_source:
                        train["delay_source"] = delay_source

                    planned_dt = parse_time_code(train["planned_departure_raw"])
                    actual_dt = parse_time_code(train["actual_departure_raw"])
                    if planned_dt and actual_dt:
                        delay_delta = actual_dt - planned_dt
                        delay_minutes = int(delay_delta.total_seconds() // 60)
                        train["delay_minutes"] = delay_minutes

        trains_info_sorted = sorted(trains_info, key=lambda x: x["planned_departure_time"] or "")

        latest_trains_info = trains_info_sorted

        print(f"Data updated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {len(latest_trains_info)} trains found.")

        time.sleep(UPDATE_INTERVAL)

@app.route("/json")
def json_endpoint():
    return Response(json.dumps(latest_trains_info, indent=4), mimetype='application/json')

@app.route("/metrics")
def metrics():
    # Produce Prometheus metrics output from latest_trains_info
    # We'll output:
    # 1) Planned departure time as a unix timestamp
    # 2) Actual departure time as a unix timestamp (if available)
    # 3) Delay in minutes (if available)
    # 4) Planned and actual platforms
    # 5) Event statuses and delay sources

    metric_lines = []
    metric_lines.append("# HELP train_planned_departure_timestamp_seconds Planned departure time as a unix timestamp")
    metric_lines.append("# TYPE train_planned_departure_timestamp_seconds gauge")

    metric_lines.append("# HELP train_actual_departure_timestamp_seconds Actual departure time as a unix timestamp")
    metric_lines.append("# TYPE train_actual_departure_timestamp_seconds gauge")

    metric_lines.append("# HELP train_delay_minutes Delay in minutes")
    metric_lines.append("# TYPE train_delay_minutes gauge")

    metric_lines.append("# HELP train_planned_departure_platform Planned departure platform number")
    metric_lines.append("# TYPE train_planned_departure_platform gauge")

    metric_lines.append("# HELP train_actual_departure_platform Actual departure platform number")
    metric_lines.append("# TYPE train_actual_departure_platform gauge")

    metric_lines.append("# HELP train_departure_event_status Event status for departure")
    metric_lines.append("# TYPE train_departure_event_status gauge")

    metric_lines.append("# HELP train_delay_source Source of delay information")
    metric_lines.append("# TYPE train_delay_source gauge")

    for train in latest_trains_info:
        def clean_label(value):
            if value is None:
                return ""
            return str(value).replace("\\", "\\\\").replace('"', '\\"')

        labels = (
            f'train_id="{clean_label(train["trip_id"])}",'
            f'train_type="{clean_label(train["train_type"])}",'
            f'train_number="{clean_label(train["train_number"])}",'
            f'line="{clean_label(train["line"])}",'
            f'destination="{clean_label(train["destination"])}"'
        )

        planned_dt = parse_time_code(train["planned_departure_raw"])
        if planned_dt:
            planned_ts = int(planned_dt.timestamp())
            metric_lines.append(f'train_planned_departure_timestamp_seconds{{{labels}}} {planned_ts}')
            actual_dt = parse_time_code(train["actual_departure_raw"]) if train["actual_departure_raw"] else None
            if actual_dt:
                actual_ts = int(actual_dt.timestamp())
                metric_lines.append(f'train_actual_departure_timestamp_seconds{{{labels}}} {actual_ts}')
            else:
                metric_lines.append(f'train_actual_departure_timestamp_seconds{{{labels}}} {planned_ts}')

        if train["delay_minutes"] is not None:
            metric_lines.append(f'train_delay_minutes{{{labels}}} {train["delay_minutes"]}')

        planned_dp_platform = train.get("planned_departure_platform")
        if planned_dp_platform and planned_dp_platform.isdigit():
            metric_lines.append(f'train_planned_departure_platform{{{labels}}} {int(planned_dp_platform)}')

        actual_dp_platform = train.get("actual_departure_platform")
        if actual_dp_platform and actual_dp_platform.isdigit():
            metric_lines.append(f'train_actual_departure_platform{{{labels}}} {int(actual_dp_platform)}')

        departure_event_status = train.get("departure_event_status")
        if departure_event_status:
            status_mapping = {"p": 1, "a": 2, "c": 3}
            status_code = status_mapping.get(departure_event_status.lower(), 0)
            metric_lines.append(f'train_departure_event_status{{{labels}}} {status_code}')

        delay_source = train.get("delay_source")
        if delay_source:
            delay_source_mapping = {
                "L": 1,  # LEIBIT
                "NA": 2, # RISNE AUT
                "NM": 3, # RISNE MAN
                "V": 4,  # VDV Prognosen
                "IA": 5, # ISTP AUT
                "IM": 6, # ISTP MAN
                "A": 7   # AUTOMATIC PROGNOSIS
            }
            source_code = delay_source_mapping.get(delay_source.upper(), 0)
            metric_lines.append(f'train_delay_source{{{labels}}} {source_code}')

    return Response("\n".join(metric_lines) + "\n", mimetype="text/plain")

if __name__ == "__main__":
    fetch_thread = threading.Thread(target=fetch_and_update_data, daemon=True)
    fetch_thread.start()
    app.run(host="0.0.0.0", port=8080)
