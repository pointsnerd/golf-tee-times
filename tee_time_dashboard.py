import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from curl_cffi import requests

# --- Course Configuration Registry ---
CHRONOGOLF_COURSES = [
    {
        "name": "D'Arcy Ranch Golf Club",
        "club_slug": "d-arcy-ranch-golf-club",
        "ids": ["da3eb64e-8ff4-4a43-9958-2e36f108ce4e", "5a18dff5-d436-4574-b25f-75ad6fd82bd1"],
        "rate_18_cart": "$130.00",
        "rate_9_cart": "$70.00",
        "color": "#1E3A8A"  # Deep Blue
    },
    {
        "name": "River Spirit Golf Club",
        "club_slug": "river-spirit-golf-club",
        "ids": [
            "4708f6de-dd55-4722-8613-b305d7c32438", "dfb35728-e416-46be-8904-6b053dc4c1ca",
            "fcad2564-a611-4137-9c38-1d02abe77b78", "c4924955-d232-4d52-bd90-6ba5eeea88d1",
            "04beb0e0-6718-47a5-8a47-7e5aa076505b", "457a26d8-1924-48c0-936b-d19af99e3bcd"
        ],
        "rate_18_cart": "$180.00",
        "rate_9_cart": "$95.00",
        "color": "#9A3412"  # Rust Amber
    },
    {
        "name": "Sundre Golf Club",
        "club_slug": "sundre-golf-club",
        "ids": ["804f0be1-3772-4dcb-bf8a-540dd4727ba0"],
        "rate_18_cart": "$140.70",
        "rate_9_cart": "$80.00",
        "color": "#581C87"  # Deep Purple
    },
    {
        "name": "Sirocco Golf Club",
        "club_slug": "sirocco-golf-club",
        "ids": ["eb90994d-d150-4234-b0c3-67c239a78cf3"],
        "rate_18_cart": "$157.50",
        "rate_9_cart": "$85.00",
        "color": "#9D174D"  # Berry Rose
    }
]

COURSE_COLOR_MAP = {c["name"]: c["color"] for c in CHRONOGOLF_COURSES}

# Static verified 18-hole and 9-hole Adult with Cart pricing
COURSE_RATES_18 = {
    "d-arcy-ranch-golf-club": "$130.00",
    "river-spirit-golf-club": "$180.00",
    "sundre-golf-club": "$140.70",
    "sirocco-golf-club": "$157.50"
}

COURSE_RATES_9 = {
    "d-arcy-ranch-golf-club": "$70.00",
    "river-spirit-golf-club": "$95.00",
    "sundre-golf-club": "$80.00",
    "sirocco-golf-club": "$85.00"
}

def parse_slot_time(item):
    """Extract local tee time."""
    raw = item.get("start_time") or item.get("time")
    if not raw:
        return None
    raw_str = str(raw).strip()
    
    if ":" in raw_str and "T" not in raw_str:
        try:
            parts = raw_str.split(":")
            return datetime.strptime(f"{int(parts[0]):02d}:{parts[1]}", "%H:%M").time()
        except Exception:
            pass

    if "T" in raw_str:
        try:
            if raw_str.endswith("Z"):
                dt = datetime.fromisoformat(raw_str.replace("Z", "+00:00"))
                return dt.astimezone(ZoneInfo("America/Edmonton")).time()
            else:
                return datetime.fromisoformat(raw_str).time()
        except Exception:
            pass
    return None

def evaluate_chronogolf_slot(item, requested_spots, selected_round_length, club_slug):
    """
    Evaluates bookability using Chronogolf's default_price, player limits, and selected round length (18 or 9).
    Returns (is_valid, spots_display, price_str, holes_display)
    """
    if item.get("frozen") is True or item.get("out_of_capacity") is True:
        return False, "", "", ""

    # 1. Capacity resolution
    max_size = item.get("max_player_size")
    min_size = item.get("min_player_size", 1)

    if not max_size:
        if "player_counts" in item and isinstance(item["player_counts"], list):
            valid_p = [int(p) for p in item["player_counts"] if str(p).isdigit()]
            if valid_p:
                max_size = max(valid_p)
                min_size = min(valid_p)

    if not max_size:
        options = item.get("green_fee_options", [])
        if isinstance(options, list):
            for opt in options:
                if isinstance(opt, dict) and "player_counts" in opt and isinstance(opt["player_counts"], list):
                    valid_p = [int(p) for p in opt["player_counts"] if str(p).isdigit()]
                    if valid_p:
                        max_size = max(valid_p)
                        min_size = min(valid_p)
                        break

    if not max_size:
        max_size = 4

    if max_size < requested_spots:
        return False, "", "", ""

    # 2. Holes validation
    bookable_holes = set()
    default_price = item.get("default_price", {})
    
    if isinstance(default_price, dict):
        dp_holes = default_price.get("bookable_holes")
        if isinstance(dp_holes, list):
            bookable_holes.update(dp_holes)
        elif isinstance(dp_holes, int):
            bookable_holes.add(dp_holes)

    course_obj = item.get("course", {})
    c_holes = course_obj.get("bookable_holes", [])
    if isinstance(c_holes, list):
        bookable_holes.update(c_holes)
    elif isinstance(c_holes, int):
        bookable_holes.add(c_holes)

    if not bookable_holes and "holes" in item:
        h_val = item.get("holes")
        if isinstance(h_val, list):
            bookable_holes.update(h_val)
        elif isinstance(h_val, int):
            bookable_holes.add(h_val)

    if not bookable_holes:
        bookable_holes.add(18)

    if selected_round_length not in bookable_holes:
        return False, "", "", ""

    # 3. Adult Public Rate with Cart Assignment
    if selected_round_length == 18:
        price_str = COURSE_RATES_18.get(club_slug, "$130.00")
    else:
        price_str = COURSE_RATES_9.get(club_slug, "$70.00")

    if 9 in bookable_holes and 18 in bookable_holes:
        holes_display = "9 / 18"
    elif 18 in bookable_holes:
        holes_display = "18"
    else:
        holes_display = "9"

    spots_display = f"{min_size}-{max_size}" if min_size != max_size else f"{max_size}"
    return True, spots_display, price_str, holes_display

def fetch_course_teetimes(session, course, date_str):
    """Fetch public tee sheet using Chrome TLS impersonation."""
    base_url = "https://www.chronogolf.com/marketplace/v2/teetimes"
    params = {
        "start_date": date_str,
        "course_ids": ",".join(course["ids"]),
        "holes": "9,18",
        "page": "1"
    }
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "referer": f"https://www.chronogolf.ca/club/{course['club_slug']}",
        "origin": "https://www.chronogolf.ca",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site"
    }
    
    try:
        resp = session.get(
            base_url,
            params=params,
            headers=headers,
            impersonate="chrome124",
            timeout=10
        )
        status = resp.status_code
        if status == 200:
            payload = resp.json()
            items = []
            if isinstance(payload, dict):
                items = payload.get("teetimes", payload.get("data", []))
            elif isinstance(payload, list):
                items = payload
            return items, f"HTTP 200 (Total records: {len(items)})"
        else:
            return [], f"HTTP {status}"
    except Exception as e:
        return [], f"Error: {e}"

def get_target_weekend_dates(num_weeks=2):
    """Calculate upcoming Friday, Saturday, and Sunday dates using Calgary local time."""
    try:
        today = datetime.now(ZoneInfo("America/Edmonton")).date()
    except Exception:
        today = datetime.now().date()
        
    target_dates = []
    for day_offset in range(num_weeks * 7):
        candidate = today + timedelta(days=day_offset)
        if candidate.weekday() in [4, 5, 6]:
            target_dates.append(candidate)
    return target_dates

# --- UI Setup ---
st.set_page_config(page_title="First Right of Refusal Golf Tee Sheet", layout="wide")
st.title("⛳ First Right of Refusal Golf Tee Sheet")

# Sidebar Controls
st.sidebar.header("Filter Settings")
time_filter = st.sidebar.radio("Tee Time", options=["AM", "PM", "All Day"], index=0)
min_spots = st.sidebar.selectbox("Minimum Open Spots", options=[1, 2, 3, 4], index=0)
round_length = st.sidebar.radio("Round Length", options=[18, 9], index=0)

selected_courses = st.sidebar.multiselect(
    "Select Courses",
    options=[c["name"] for c in CHRONOGOLF_COURSES],
    default=[c["name"] for c in CHRONOGOLF_COURSES]
)

if st.button("🔄 Refresh Data (Force Clear Cache)"):
    st.cache_data.clear()
    st.rerun()

# --- Data Fetching & Processing ---
@st.cache_data(ttl=60)
def load_all_data(requested_spots, selected_holes, selected_time_period):
    weekend_dates = get_target_weekend_dates(num_weeks=2)
    rows = []
    diagnostics = []
    session = requests.Session()
    noon = time(12, 0)

    for course in CHRONOGOLF_COURSES:
        if course["name"] not in selected_courses:
            continue
        for date_obj in weekend_dates:
            date_str = date_obj.strftime("%Y-%m-%d")
            raw_items, diag_msg = fetch_course_teetimes(session, course, date_str)
            diagnostics.append(f"{course['name']} [{date_str}]: {diag_msg}")
            
            if not isinstance(raw_items, list):
                continue

            seen_times = set()

            for item in raw_items:
                if not isinstance(item, dict):
                    continue

                t_val = parse_slot_time(item)
                if not t_val:
                    continue

                if selected_time_period == "AM" and t_val >= noon:
                    continue
                elif selected_time_period == "PM" and t_val < noon:
                    continue

                is_valid, spots_display, price_str, holes_display = evaluate_chronogolf_slot(
                    item, requested_spots, selected_holes, course["club_slug"]
                )
                
                if not is_valid:
                    continue

                time_key = (course["name"], date_str, t_val.strftime("%H:%M"))
                if time_key in seen_times:
                    continue
                seen_times.add(time_key)

                booking_url = f"https://www.chronogolf.ca/club/{course['club_slug']}#?date={date_str}"

                rows.append({
                    "Course": course["name"],
                    "Date": date_str,
                    "DateObj": date_obj,
                    "Day": date_obj.strftime("%A"),
                    "Time": t_val.strftime("%I:%M %p"),
                    "Open Spots": spots_display,
                    "Price (Adult w/ Cart)": price_str,
                    "Holes": holes_display,
                    "Book": booking_url,
                    "RawTime": t_val
                })
    return rows, diagnostics

with st.spinner("Fetching live tee sheets..."):
    results, diag_logs = load_all_data(min_spots, round_length, time_filter)

COLUMN_CONFIG = {
    "Course": st.column_config.TextColumn("Course", alignment="left"),
    "Time": st.column_config.TextColumn("Time", alignment="center"),
    "Open Spots": st.column_config.TextColumn("Open Spots", alignment="center"),
    "Price (Adult w/ Cart)": st.column_config.TextColumn("Price (Adult w/ Cart)", alignment="center"),
    "Holes": st.column_config.TextColumn("Holes", alignment="center"),
    "Book": st.column_config.LinkColumn("Book", display_text="Book Now ↗", alignment="center")
}

def color_courses(val):
    color = COURSE_COLOR_MAP.get(val, "#374151")
    return f"background-color: {color}; color: white; font-weight: bold; border-radius: 4px; padding: 3px 6px;"

target_dates = get_target_weekend_dates(num_weeks=2)

if results:
    df = pd.DataFrame(results)
    
    col1, col2, col3 = st.columns(3)
    metric_label = f"{time_filter} Times Available" if time_filter != "All Day" else "Total Times Available"
    col1.metric(metric_label, len(df))
    col2.metric("Courses Monitored", len(df["Course"].unique()))
    col3.metric("Dates Tracked", len(target_dates))

    st.write("---")

    for i in range(0, len(target_dates), 3):
        weekend_slice = target_dates[i:i+3]
        cols = st.columns(3)
        
        for idx, date_obj in enumerate(weekend_slice):
            date_str = date_obj.strftime("%Y-%m-%d")
            formatted_date_header = date_obj.strftime("%A, %B %d")
            
            day_matches = df[df["Date"] == date_str]
            
            with cols[idx]:
                with st.container(border=True):
                    st.subheader(formatted_date_header)
                    
                    if day_matches.empty:
                        empty_label = f"No {time_filter} times open." if time_filter != "All Day" else "No times open."
                        st.caption(empty_label)
                    else:
                        course_counts = day_matches["Course"].value_counts()
                        
                        for course_name in selected_courses:
                            count = course_counts.get(course_name, 0)
                            color = COURSE_COLOR_MAP.get(course_name, "#374151")
                            badge_style = f"display: inline-block; width: 10px; height: 10px; border-radius: 50%; background-color: {color}; margin-right: 6px;"
                            
                            if count > 0:
                                st.markdown(
                                    f'<div style="margin-bottom: 4px;">'
                                    f'<span style="{badge_style}"></span>'
                                    f'<strong>{course_name}</strong>: '
                                    f'<span style="color: #22C55E; font-weight: bold;">{count} Available</span>'
                                    f'</div>',
                                    unsafe_allow_html=True
                                )
                            else:
                                st.markdown(
                                    f'<div style="margin-bottom: 4px; opacity: 0.5;">'
                                    f'<span style="{badge_style}"></span>'
                                    f'<span>{course_name}</span>: 0 Available'
                                    f'</div>',
                                    unsafe_allow_html=True
                                )
                        
                        with st.expander(f"View {len(day_matches)} Times & Book"):
                            clean_day_df = day_matches.sort_values(by="RawTime")[["Course", "Time", "Open Spots", "Price (Adult w/ Cart)", "Holes", "Book"]]
                            styled_day = clean_day_df.style.map(color_courses, subset=["Course"])
                            st.dataframe(
                                styled_day,
                                column_config=COLUMN_CONFIG,
                                use_container_width=True,
                                hide_index=True
                            )
else:
    no_results_label = f"No {time_filter} tee times found matching your criteria, or tee sheets are not yet open for these dates." if time_filter != "All Day" else "No tee times found matching your criteria, or tee sheets are not yet open for these dates."
    st.info(no_results_label)

with st.expander("🛠 API Connection Diagnostics"):
    for log in diag_logs:
        st.text(log)