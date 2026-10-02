import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from curl_cffi import requests

# --- Course Configuration Registry ---
CHRONOGOLF_COURSES = [
    {
        "name": "D'Arcy Ranch Golf Club",
        "club_slug": "d-arcy-ranch-golf-club",
        "ids": ["da3eb64e-8ff4-4a43-9958-2e36f108ce4e", "5a18dff5-d436-4574-b25f-75ad6fd82bd1"],
        "holes": "9,18",
        "color": "#1E3A8A"  # Deep Blue
    },
    {
        "name": "Lynx Ridge Golf Club",
        "club_slug": "lynx-ridge-golf-club",
        "ids": ["f0ffad1a-9857-4396-ba29-b3b6437ada54"],
        "holes": "9,18,19",
        "color": "#065F46"  # Forest Green
    },
    {
        "name": "River Spirit Golf Club",
        "club_slug": "river-spirit-golf-club",
        "ids": [
            "4708f6de-dd55-4722-8613-b305d7c32438", "dfb35728-e416-46be-8904-6b053dc4c1ca",
            "fcad2564-a611-4137-9c38-1d02abe77b78", "c4924955-d232-4d52-bd90-6ba5eeea88d1",
            "04beb0e0-6718-47a5-8a47-7e5aa076505b", "457a26d8-1924-48c0-936b-d19af99e3bcd"
        ],
        "holes": "9,18",
        "color": "#9A3412"  # Rust Amber
    },
    {
        "name": "Sundre Golf Club",
        "club_slug": "sundre-golf-club",
        "ids": ["804f0be1-3772-4dcb-bf8a-540dd4727ba0"],
        "holes": "9,18",
        "color": "#581C87"  # Deep Purple
    },
    {
        "name": "Fairmont Banff Springs",
        "club_slug": "fairmont-banff-springs-golf-course",
        "ids": [
            "defd9bf6-3d27-40e8-b511-db6f6d1a9318", "31781402-a719-43d8-ae00-fb41a99dce2f",
            "22476e2b-1c0a-4470-86bd-d55c8898b478"
        ],
        "holes": "9,18",
        "color": "#0F766E"  # Dark Teal
    },
    {
        "name": "Sirocco Golf Club",
        "club_slug": "sirocco-golf-club",
        "ids": ["eb90994d-d150-4234-b0c3-67c239a78cf3"],
        "holes": "9,18",
        "color": "#9D174D"  # Berry Rose
    }
]

COURSE_COLOR_MAP = {c["name"]: c["color"] for c in CHRONOGOLF_COURSES}

def extract_open_spots(item):
    """Determine open spots accurately from Chronogolf schema variations."""
    if "open_slots" in item and item["open_slots"] is not None:
        return int(item["open_slots"])
    
    if "player_counts" in item and isinstance(item["player_counts"], list) and len(item["player_counts"]) > 0:
        return max(item["player_counts"])
    
    max_cap = item.get("max_player_count", 4)
    if "booked_players" in item and isinstance(item["booked_players"], list):
        return max(0, max_cap - len(item["booked_players"]))
    
    options = item.get("green_fee_options", [])
    if options and isinstance(options, list):
        counts = [opt.get("player_count", 0) for opt in options if isinstance(opt, dict)]
        if counts:
            return max(counts)

    return item.get("players", 4)

def fetch_course_teetimes(session, course, date_str):
    """Fetch public tee sheet for a course on a given date using Chrome TLS impersonation."""
    base_url = "https://www.chronogolf.com/marketplace/v2/teetimes"
    params = {
        "start_date": date_str,
        "course_ids": ",".join(course["ids"]),
        "holes": course["holes"],
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
            return items, f"HTTP 200 (Found {len(items)} slots)"
        else:
            return [], f"HTTP {status}"
    except Exception as e:
        return [], f"Error: {e}"

def get_target_weekend_dates(num_weeks=2):
    """Calculate upcoming Friday, Saturday, and Sunday dates using local Calgary time."""
    try:
        today = datetime.now(ZoneInfo("America/Edmonton")).date()
    except Exception:
        today = datetime.now().date()
        
    target_dates = []
    for day_offset in range(num_weeks * 7):
        candidate = today + timedelta(days=day_offset)
        # Friday (4), Saturday (5), Sunday (6)
        if candidate.weekday() in [4, 5, 6]:
            target_dates.append(candidate)
    return target_dates

# --- UI Setup ---
st.set_page_config(page_title="First Right of Refusal Golf Tee Sheet", layout="wide")
st.title("⛳ First Right of Refusal Golf Tee Sheet")

# Sidebar Controls
st.sidebar.header("Filter Settings")
max_time = st.sidebar.time_input("Latest Tee Time (Morning Cutoff)", datetime.strptime("11:59", "%H:%M").time())
min_spots = st.sidebar.selectbox("Minimum Open Spots", options=[1, 2, 3, 4], index=3)
selected_courses = st.sidebar.multiselect(
    "Select Courses",
    options=[c["name"] for c in CHRONOGOLF_COURSES],
    default=[c["name"] for c in CHRONOGOLF_COURSES]
)

if st.button("🔄 Refresh Data"):
    st.cache_data.clear()

# --- Data Fetching & Processing ---
@st.cache_data(ttl=180)
def load_all_data():
    weekend_dates = get_target_weekend_dates(num_weeks=2)
    rows = []
    diagnostics = []
    
    # Establish TLS-impersonating session
    session = requests.Session()

    for course in CHRONOGOLF_COURSES:
        if course["name"] not in selected_courses:
            continue
        for date_obj in weekend_dates:
            date_str = date_obj.strftime("%Y-%m-%d")
            raw_items, diag_msg = fetch_course_teetimes(session, course, date_str)
            diagnostics.append(f"{course['name']} [{date_str}]: {diag_msg}")
            
            if not isinstance(raw_items, list):
                continue

            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                
                start_time_str = item.get("start_time") or item.get("time")
                if not start_time_str:
                    continue
                
                try:
                    if "T" in str(start_time_str):
                        t_val = datetime.fromisoformat(str(start_time_str)).time()
                    else:
                        t_val = datetime.strptime(str(start_time_str)[:5], "%H:%M").time()
                except Exception:
                    continue
                
                if t_val <= max_time:
                    open_spots = extract_open_spots(item)
                    
                    if isinstance(open_spots, int) and open_spots < min_spots:
                        continue

                    green_fee = item.get("green_fee") or item.get("price") or 0
                    price_str = f"${green_fee / 100:.2f}" if isinstance(green_fee, (int, float)) and green_fee > 500 else f"${green_fee}"
                    booking_url = f"https://www.chronogolf.ca/club/{course['club_slug']}#?date={date_str}"

                    rows.append({
                        "Course": course["name"],
                        "Date": date_str,
                        "DateObj": date_obj,
                        "Day": date_obj.strftime("%A"),
                        "Time": t_val.strftime("%I:%M %p"),
                        "Open Spots": open_spots,
                        "Price": price_str,
                        "Holes": item.get("holes", 18),
                        "Book": booking_url,
                        "RawTime": t_val
                    })
    return rows, diagnostics

with st.spinner("Fetching live tee sheets..."):
    results, diag_logs = load_all_data()

COLUMN_CONFIG = {
    "Course": st.column_config.TextColumn("Course", alignment="left"),
    "Time": st.column_config.TextColumn("Time", alignment="center"),
    "Open Spots": st.column_config.NumberColumn("Open Spots", alignment="center"),
    "Price": st.column_config.TextColumn("Price", alignment="center"),
    "Holes": st.column_config.NumberColumn("Holes", alignment="center"),
    "Book": st.column_config.LinkColumn("Book", display_text="Book Now ↗", alignment="center")
}

def color_courses(val):
    color = COURSE_COLOR_MAP.get(val, "#374151")
    return f"background-color: {color}; color: white; font-weight: bold; border-radius: 4px; padding: 3px 6px;"

target_dates = get_target_weekend_dates(num_weeks=2)

if results:
    df = pd.DataFrame(results)
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Morning Times Available", len(df))
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
                        st.caption("No morning times open.")
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
                            clean_day_df = day_matches.sort_values(by="RawTime")[["Course", "Time", "Open Spots", "Price", "Holes", "Book"]]
                            styled_day = clean_day_df.style.map(color_courses, subset=["Course"])
                            st.dataframe(
                                styled_day,
                                column_config=COLUMN_CONFIG,
                                use_container_width=True,
                                hide_index=True
                            )
else:
    st.info("No morning tee times found matching your criteria, or tee sheets are not yet open for these dates.")

with st.expander("🛠️️ API Connection Diagnostics"):
    for log in diag_logs:
        st.text(log)