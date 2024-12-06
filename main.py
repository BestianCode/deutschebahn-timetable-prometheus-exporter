import os
import requests
import xml.etree.ElementTree as ET
import json

url = f"https://apis.deutschebahn.com/db-api-marketplace/apis/timetables/v1/plan/{os.getenv('DB_STATION')}/241206/19"

headers = {
    "DB-Client-Id": os.getenv('DB_CLIENT_ID'),
    "DB-Api-Key": os.getenv('DB_CLIENT_SECRET'),
    "accept": "application/xml"
}

response = requests.get(url, headers=headers)

root = ET.fromstring(response.text)

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

data = etree_to_dict(root)
#print(json.dumps(data, indent=4, ensure_ascii=False))

trains_info = []

for entry in data["timetable"]["s"]:
    tl = entry.get("tl", {})
    dp = entry.get("dp", {})

    # Train type (category)
    train_type = tl.get("@c")

    # Line number
    line_number = dp.get("@l")

    # Departure time (raw format)
    departure_time_str = dp.get("@pt")

    # Convert departure time (if desired) to human-readable format:
    # departure_time_str is in format YYMMDDHHmm, e.g. "2412061532"
    # Let's parse it:
    # year = 20YY (assuming 20 prefix)
    # month = MM
    # day = DD
    # hour = HH
    # minute = mm
    # For this example, we'll just keep the raw string or parse it:
    if departure_time_str and len(departure_time_str) == 10:
        yy = departure_time_str[0:2]
        mm = departure_time_str[2:4]
        dd = departure_time_str[4:6]
        hh = departure_time_str[6:8]
        minu = departure_time_str[8:10]
        # Assume "20YY" for year
        year = "20" + yy
        departure_time_readable = f"{year}-{mm}-{dd} {hh}:{minu}"
    else:
        departure_time_readable = departure_time_str

    # Destination station:
    route = dp.get("@ppth", "")
    # The final station is the last in the split by '|'
    stations = route.split("|")
    destination = stations[-1] if stations else None

    # Delay:
    # Since no explicit delay attribute is shown, set delay to None or a default value.
    delay = None

    trains_info.append({
        "line": line_number,
        "departure_time": departure_time_readable,
        "train_type": train_type,
        "delay": delay,
        "destination": destination
    })

print(json.dumps(trains_info, indent=4, ensure_ascii=False))
