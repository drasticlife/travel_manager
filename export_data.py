import json
import maps_page
import trip

def main():
    conn = trip.connect()
    places = maps_page.collect(conn)
    days = maps_page.collect_days(conn)
    route = maps_page.collect_route(conn)
    items = maps_page.collect_items(conn)
    timetable = maps_page.collect_timetable(conn)
    tips = maps_page.collect_tips(conn)
    
    data = {
        "PLACES": places,
        "DAYS": days,
        "ROUTE": route,
        "ITEMS": items,
        "TIMETABLE": timetable,
        "STATIONS": maps_page.PLACE_STATION,
        "TIPS": tips,
        "LABELS": maps_page.STATUS_LABEL,
        "TOTAL": len(places),
        "API_KEY": maps_page.get_google_maps_key()
    }
    
    js_content = "window.APP_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n"
    
    with open("data.js", "w", encoding="utf-8") as f:
        f.write(js_content)
    
    print("Exported data.js successfully.")

if __name__ == "__main__":
    main()
