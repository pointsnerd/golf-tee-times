import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from curl_cffi import requests

# --- Course Configuration Registry ---
CHRONOGOLF_COURSES = [
    {
        "name": "D'Arcy Ranch Golf Club",
        "short_name": "D'Arcy Ranch",
        "club_slug": "d-arcy-ranch-golf-club",
        "ids": ["da3eb64e-8ff4-4a43-9958-2e36f108ce4e", "5a18dff5-d436-4574-b25f-75ad6fd82bd1"],
        "rate_18_cart": "$130.00",
        "rate_9_cart": "$70.00",
        "color": "#1E3A8A"  # Deep Blue
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
        "color": "#9A3412"  # Rust Amber
    },
    {
        "name": "Sundre Golf Club",
        "short_name": "Sundre",
        "club_slug": "sundre-golf-club",
        "ids": ["804f0be1-3772-4dcb-bf8a-540dd4727ba0"],
        "rate_18_cart": "$140.70",
        "rate_9_cart": "$80.00",
        "color": "#581C87"  # Deep Purple
    },
    {
        "name": "Sirocco Golf Club",
        "short_name": "Sirocco",
        "club_slug": "sirocco-golf-club",
        "ids": ["eb90994d-d150-4234-b0c3-67c239a78cf3"],
        "rate_18_cart": "$157.50",
        "rate_9_cart": "$85.00",
        "color": "#9D174D"  # Berry Rose
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

def get_target_dates(num_days=14):
    """Generate upcoming dates starting from current local day."""
    try:
        today = datetime.now(ZoneInfo("America/Edmonton")).date()
    except Exception:
        today = datetime.now().date()
    return [today + timedelta(days=offset) for offset in range(num_days)]

# --- UI Setup ---
st.set_page_config(page_title="First Right of Refusal Golf Tee Sheet", layout="wide")

# Custom CSS for UI spacing
st.markdown("""
<style>
    div[data-testid="stHorizontalBlock"] {
        gap: 0.5rem;
    }
    .metric-card {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 10px 14px;
        text-align: center;
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
@st.cache_data(ttl=60)
def load_all_data(requested_spots, selected_holes, selected_time_period):
    target_dates = get_target_dates(num_days=14)
    rows = []
    diagnostics = []
    session = requests.Session()
    noon = time(12, 0)

    for course in CHRONOGOLF_COURSES:
        if course["name"] not in selected_courses:
            continue
        for date_obj in target_dates:
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
    "Course": st.column_config.TextColumn("Course", width="medium"),
    "Time": st.column_config.TextColumn("Time", width="small"),
    "Open Spots": st.column_config.TextColumn("Open Spots", width="small"),
    "Price (Adult w/ Cart)": st.column_config.TextColumn("Price (Adult w/ Cart)", width="small"),
    "Holes": st.column_config.TextColumn("Holes", width="small"),
    "Book": st.column_config.LinkColumn("Book", display_text="Book Now ↗", width="small")
}

def color_courses(val):
    color = COURSE_COLOR_MAP.get(val, "#374151")
    return f"background-color: {color}; color: white; font-weight: bold; border-radius: 4px; padding: 3px 8px;"

target_dates = get_target_dates(num_days=14)

if results:
    df = pd.DataFrame(results)

    # Top-level KPI overview
    c1, c2, c3 = st.columns(3)
    metric_label = f"{time_filter} Times Available" if time_filter != "All Day" else "Total Times Available"
    c1.metric(metric_label, len(df))
    c2.metric("Courses Monitored", len(df["Course"].unique()))
    c3.metric("Days Tracked", len(target_dates))

    st.write("---")
    st.subheader("📅 14-Day Availability Timeline")

    # Group counts per date
    day_counts = df["Date"].value_counts().to_dict()

    # Pre-select the first date that has open tee times (fallback to today)
    dates_with_times = [d.strftime("%Y-%m-%d") for d in target_dates if day_counts.get(d.strftime("%Y-%m-%d"), 0) > 0]
    default_selected = dates_with_times[0] if dates_with_times else target_dates[0].strftime("%Y-%m-%d")

    # Format options for the pill selector
    date_options = [d.strftime("%Y-%m-%d") for d in target_dates]

    def format_date_pill(d_str):
        d_obj = datetime.strptime(d_str, "%Y-%m-%d")
        cnt = day_counts.get(d_str, 0)
        day_label = d_obj.strftime("%a %b %d")
        return f"{day_label} ({cnt})" if cnt > 0 else f"{day_label} (–)"

    selected_date = st.pills(
        "Select Date to View Tee Sheet:",
        options=date_options,
        default=default_selected,
        format_func=format_date_pill
    )

    if selected_date:
        sel_dt = datetime.strptime(selected_date, "%Y-%m-%d")
        day_matches = df[df["Date"] == selected_date]

        st.markdown(f"### 📋 Tee Sheet: **{sel_dt.strftime('%A, %B %d, %Y')}**")

        # Row of Course Metric Cards for this selected day
        course_cols = st.columns(len(selected_courses))
        course_counts = day_matches["Course"].value_counts() if not day_matches.empty else {}

        for idx, course_name in enumerate(selected_courses):
            cnt = course_counts.get(course_name, 0)
            color = COURSE_COLOR_MAP.get(course_name, "#374151")
            with course_cols[idx]:
                with st.container(border=True):
                    st.markdown(
                        f"<div style='border-left: 4px solid {color}; padding-left: 8px;'>"
                        f"<span style='font-size: 13px; color: #9CA3AF;'>{course_name}</span><br/>"
                        f"<strong style='font-size: 20px; color: {'#22C55E' if cnt > 0 else '#6B7280'};'>{cnt} Times</strong>"
                        f"</div>",
                        unsafe_allow_html=True
                    )

        st.write("")

        # Full-width Tee Sheet Table
        if day_matches.empty:
            st.info(f"No {time_filter} tee times found for {sel_dt.strftime('%A, %B %d')}.")
        else:
            clean_df = day_matches.sort_values(by="RawTime")[
                ["Course", "Time", "Open Spots", "Price (Adult w/ Cart)", "Holes", "Book"]
            ]
            styled_df = clean_df.style.map(color_courses, subset=["Course"])
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