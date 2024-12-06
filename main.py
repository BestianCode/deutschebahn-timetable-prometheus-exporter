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
        d[t.tag].update(('@' + k, v) for k, v in t.attrib.items())
    if t.text:
        text = t.text.strip()
        if children or t.attrib:
            if text:
                d[t.tag]['#text'] = text
        else:
            d[t.tag] = text
    return d

def get_train_data(date_str, hour_str):
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

for date_str, hour_str in dates_hours:
    data = get_train_data(date_str, hour_str)
    for entry in data.get("timetable", {}).get("s", []):
        tl = entry.get("tl", {})
        dp = entry.get("dp", {})
        train_type = tl.get("@c")
        line_number = dp.get("@l")
        # Add prefix 'S' if line_number is a single digit between '1' and '9'
        if line_number and line_number.isdigit() and 1 <= int(line_number) <= 9:
            line_number = f"S{line_number}"
        departure_time_str = dp.get("@pt")
        if departure_time_str and len(departure_time_str) == 10:
            yy = departure_time_str[0:2]
            mm = departure_time_str[2:4]
            dd = departure_time_str[4:6]
            hh = departure_time_str[6:8]
            minu = departure_time_str[8:10]
            year = "20" + yy
            # Keep only time part
            departure_time_readable = f"{hh}:{minu}"
            departure_datetime = datetime.strptime(f"{year}-{mm}-{dd} {hh}:{minu}", "%Y-%m-%d %H:%M")
        else:
            departure_time_readable = departure_time_str
            departure_datetime = None
        route = dp.get("@ppth", "")
        stations = route.split("|")
        destination = stations[-1] if stations else None
        delay = None
        if departure_datetime and now <= departure_datetime <= upper_limit:
            trains_info.append({
                "line": line_number,
                "departure_time": departure_time_readable,
                "train_type": train_type,
                "delay": delay,
                "destination": destination
            })

trains_info_sorted = sorted(trains_info, key=lambda x: x["departure_time"])
print(json.dumps(trains_info_sorted, indent=4, ensure_ascii=False))
