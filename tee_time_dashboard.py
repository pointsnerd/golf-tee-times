import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from curl_cffi import requests

# --- Course Configuration Registry ---
# Refined modern links-style palette: Augusta Pine, Heritage Sandstone, Heather Sage, and Clay Copper
CHRONOGOLF_COURSES = [
    {
        "name": "D'Arcy Ranch Golf Club",
        "short_name": "D'Arcy Ranch",
        "club_slug": "d-arcy-ranch-golf-club",
        "ids": ["da3eb64e-8ff4-4a43-9958-2e36f108ce4e", "5a18dff5-d436-4574-b25f-75ad6fd82bd1"],
        "rate_18_cart": "$130.00",
        "rate_9_cart": "$70.00",
        "color": "#1B4332"  # Deep Augusta Pine
    },
    {
        "name": "River Spirit Golf Club",
        "short_name": "River Spirit",
        "club_slug": "river-spirit-golf-club",
        "ids": [
            "4708f6de-dd55-4722-8613-b305d7c32438", "dfb35728-e416-46be-8904-6b053dc4c1ca",
            "fcad2564-a611-4137-9c38-1d02abe77b78", "c4924955-d232-4d52-bd90-6ba5eeea88d1",
            "04beb0e0-6718-47a5-8a47-7e5aa076505b", "457a26d8-1924-48c0-936b-d19af99e3bcd"
        ],
        "rate_18_cart": "$180.00",
        "rate_9_cart": "$95.00",
        "color": "#B45309"  # Heritage Copper Amber
    },
    {
        "name": "Sundre Golf Club",
        "short_name": "Sundre",
        "club_slug": "sundre-golf-club",
        "ids": ["804f0be1-3772-4dcb-bf8a-540dd4727ba0"],
        "rate_18_cart": "$140.70",
        "rate_9_cart": "$80.00",
        "color": "#4338CA"  # Classic Fairway Indigo
    },
    {
        "name": "Sirocco Golf Club",
        "short_name": "Sirocco",
        "club_slug": "sirocco-golf-club",
        "ids": ["eb90994d-d150-4234-b0c3-67c239a78cf3"],
        "rate_18_cart": "$157.50",
        "rate_9_cart": "$85.00",
        "color": "#0F766E"  # Juniper Sage Teal
    }
]

COURSE_COLOR_MAP = {c["name"]: c["color"] for c in CHRONOGOLF_COURSES}

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

def get_sunday_start_calendar_dates(num_weeks=2):
    """
    Builds a calendar grid where Sunday starts each week.
    Finds the most recent Sunday relative to today, then builds 14 consecutive days.
    """
    try:
        today = datetime.now(ZoneInfo("America/Edmonton")).date()
    except Exception:
        today = datetime.now().date()
        
    # Python weekday(): Monday is 0, Sunday is 6
    # Days since preceding Sunday: (weekday + 1) % 7
    days_since_sunday = (today.weekday() + 1) % 7
    start_sunday = today - timedelta(days=days_since_sunday)
    
    calendar_dates = [start_sunday + timedelta(days=i) for i in range(num_weeks * 7)]
    return calendar_dates, today

# --- UI Setup ---
st.set_page_config(page_title="First Right of Refusal Golf Tee Sheet", layout="wide")

# Theme styling: Warm slate slate background, refined typography, and clubhouse aesthetic
st.markdown("""
<style>
    /* Global layout & typography */
    .stApp {
        background-color: #0F172A;
        color: #F8FAFC;
    }
    
    /* Calendar Card styling */
    .cal-day-header {
        text-align: center;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #94A3B8;
        margin-bottom: 2px;
    }
    
    /* Center columns in the table */
    div[data-testid="stDataFrame"] td {
        font-size: 13.5px;
    }
</style>
""", unsafe_allow_html=True)

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
calendar_dates, today_date = get_sunday_start_calendar_dates(num_weeks=2)

@st.cache_data(ttl=60)
def load_all_data(requested_spots, selected_holes, selected_time_period):
    rows = []
    diagnostics = []
    session = requests.Session()
    noon = time(12, 0)

    for course in CHRONOGOLF_COURSES:
        if course["name"] not in selected_courses:
            continue
        for date_obj in calendar_dates:
            # Skip past days within the week
            if date_obj < today_date:
                continue
                
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
                    "ShortCourse": course["short_name"],
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
    "Course": st.column_config.TextColumn("Course", alignment="left", width="medium"),
    "Time": st.column_config.TextColumn("Time", alignment="center", width="small"),
    "Open Spots": st.column_config.TextColumn("Open Spots", alignment="center", width="small"),
    "Price (Adult w/ Cart)": st.column_config.TextColumn("Price (Adult w/ Cart)", alignment="center", width="small"),
    "Holes": st.column_config.TextColumn("Holes", alignment="center", width="small"),
    "Book": st.column_config.LinkColumn("Book", display_text="Book Now ↗", alignment="center", width="small")
}

def color_courses(val):
    color = COURSE_COLOR_MAP.get(val, "#334155")
    return f"background-color: {color}; color: #FFFFFF; font-weight: 600; border-radius: 4px; padding: 3px 8px;"

def center_cell(val):
    return "text-align: center;"

if results:
    df = pd.DataFrame(results)
    day_counts = df["Date"].value_counts().to_dict()

    # Metric Row
    c1, c2, c3 = st.columns(3)
    metric_label = f"{time_filter} Times Available" if time_filter != "All Day" else "Total Times Available"
    c1.metric(metric_label, len(df))
    c2.metric("Courses Monitored", len(df["Course"].unique()))
    c3.metric("Calendar Window", f"{calendar_dates[0].strftime('%b %d')} – {calendar_dates[-1].strftime('%b %d')}")

    st.write("---")
    st.subheader("📅 14-Day Calendar (Sunday – Saturday)")

    # Default to first future date with availability
    future_dates_with_times = [
        d.strftime("%Y-%m-%d") for d in calendar_dates 
        if d >= today_date and day_counts.get(d.strftime("%Y-%m-%d"), 0) > 0
    ]
    default_selected = future_dates_with_times[0] if future_dates_with_times else today_date.strftime("%Y-%m-%d")

    if "active_calendar_date" not in st.session_state:
        st.session_state["active_calendar_date"] = default_selected

    # Split into 2 rows of 7 days: Week 1 & Week 2
    weeks = [calendar_dates[0:7], calendar_dates[7:14]]
    day_abbrs = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]

    for w_idx, week_dates in enumerate(weeks, start=1):
        st.markdown(
            f"<div style='font-size: 13px; font-weight: 600; color: #94A3B8; margin-top: 6px; margin-bottom: 4px;'>"
            f"WEEK {w_idx}: {week_dates[0].strftime('%B %d')} – {week_dates[-1].strftime('%B %d')}"
            f"</div>",
            unsafe_allow_html=True
        )

        cols = st.columns(7)
        for d_idx, date_obj in enumerate(week_dates):
            d_str = date_obj.strftime("%Y-%m-%d")
            day_name = date_obj.strftime("%A")
            month_day = date_obj.strftime("%B %d").lstrip("0")
            count = day_counts.get(d_str, 0)
            is_past = date_obj < today_date
            is_active = (st.session_state["active_calendar_date"] == d_str)

            if is_past:
                card_html = (
                    f"<div style='background-color: #0F172A; border: 1px solid #1E293B; border-radius: 8px; padding: 12px 6px; text-align: center; opacity: 0.35; min-height: 105px; display: flex; flex-direction: column; justify-content: center;'>"
                    f"<div style='font-size: 11px; font-weight: 700; color: #64748B; text-transform: uppercase;'>{day_name}</div>"
                    f"<div style='font-size: 13px; font-weight: 600; color: #64748B; margin: 3px 0;'>{month_day}</div>"
                    f"<div style='font-size: 11px; color: #475569;'>Past</div>"
                    f"</div>"
                )
                with cols[d_idx]:
                    st.markdown(card_html, unsafe_allow_html=True)
            else:
                # Format:
                # Sunday
                # October 4
                # 11 Bookings Available
                if count > 0:
                    status_text = f"<span style='color: #10B981; font-weight: 700;'>{count} Bookings Available</span>"
                    border_color = "#10B981" if is_active else "#334155"
                    bg_color = "#132338" if is_active else "#1E293B"
                else:
                    status_text = "<span style='color: #64748B;'>0 Bookings Available</span>"
                    border_color = "#38BDF8" if is_active else "#1E293B"
                    bg_color = "#1A2436" if is_active else "#141D2E"

                active_glow = "box-shadow: 0 0 0 2px #38BDF8;" if is_active else ""

                card_html = (
                    f"<div style='background-color: {bg_color}; border: 1px solid {border_color}; {active_glow} border-radius: 8px; padding: 12px 6px; text-align: center; min-height: 105px; display: flex; flex-direction: column; justify-content: center; cursor: pointer;'>"
                    f"<div style='font-size: 11px; font-weight: 700; color: #94A3B8; text-transform: uppercase;'>{day_name}</div>"
                    f"<div style='font-size: 14px; font-weight: 700; color: #F8FAFC; margin: 3px 0;'>{month_day}</div>"
                    f"<div style='font-size: 11px; margin-top: 2px;'>{status_text}</div>"
                    f"</div>"
                )

                with cols[d_idx]:
                    st.markdown(card_html, unsafe_allow_html=True)
                    if st.button(f"Select {month_day}", key=f"btn_sel_{d_str}", use_container_width=True):
                        st.session_state["active_calendar_date"] = d_str
                        st.rerun()

    active_date = st.session_state["active_calendar_date"]
    sel_dt = datetime.strptime(active_date, "%Y-%m-%d")
    day_matches = df[df["Date"] == active_date]

    st.write("---")
    st.markdown(f"### 📋 Tee Sheet: **{sel_dt.strftime('%A, %B %d, %Y')}**")

    # Course breakdown header pills
    course_cols = st.columns(len(selected_courses))
    course_counts = day_matches["Course"].value_counts() if not day_matches.empty else {}

    for idx, course_name in enumerate(selected_courses):
        cnt = course_counts.get(course_name, 0)
        color = COURSE_COLOR_MAP.get(course_name, "#334155")
        with course_cols[idx]:
            with st.container(border=True):
                st.markdown(
                    f"<div style='border-left: 4px solid {color}; padding-left: 10px;'>"
                    f"<span style='font-size: 12px; font-weight: 600; color: #94A3B8;'>{course_name}</span><br/>"
                    f"<strong style='font-size: 20px; color: {'#10B981' if cnt > 0 else '#64748B'};'>{cnt} Times</strong>"
                    f"</div>",
                    unsafe_allow_html=True
                )

    st.write("")

    if day_matches.empty:
        st.info(f"No {time_filter} tee times found for {sel_dt.strftime('%A, %B %d')}.")
    else:
        clean_df = day_matches.sort_values(by="RawTime")[
            ["Course", "Time", "Open Spots", "Price (Adult w/ Cart)", "Holes", "Book"]
        ]
        styled_df = clean_df.style.map(color_courses, subset=["Course"]).map(
            center_cell, subset=["Time", "Open Spots", "Price (Adult w/ Cart)", "Holes"]
        )
        st.dataframe(
            styled_df,
            column_config=COLUMN_CONFIG,
            use_container_width=True,
            hide_index=True
        )

else:
    no_results_label = (
        f"No {time_filter} tee times found matching your criteria, or tee sheets are not yet open for these dates."
        if time_filter != "All Day"
        else "No tee times found matching your criteria, or tee sheets are not yet open for these dates."
    )
    st.info(no_results_label)

with st.expander("🛠 API Connection Diagnostics"):
    for log in diag_logs:
        st.text(log)