import random
import streamlit as st
from apis_calls.stats_api import get_bot_statistics
import pandas as pd

try:
    from settings import settings
except ImportError:
    settings = None
# Configuration
BOT_ID = settings.bot_id
random.seed(42)


def get_auth_headers():
    """Get authentication headers for API calls"""
    auth_token = st.session_state.get("id_token", "")
    return settings.build_headers(None, auth_token)


def render_metrics(time_range="today"):
    """Render metrics for a specific time range"""

    # Get actual bot statistics
    headers = get_auth_headers()
    stats_result = get_bot_statistics(BOT_ID, time_range, headers)

    if stats_result.get("success"):
        stats_data = stats_result.get("data", {})
    else:
        st.error(
            f"Failed to load statistics: {stats_result.get('error', 'Unknown error')}"
        )
        stats_data = {}

    row = st.columns(1)
    row1 = st.columns(2)
    row2 = st.columns(2)

    grid = [col.container() for col in row + row1 + row2]

    title_container = grid[0].container()
    with title_container:
        st.write(f"# Key Metrics Overview - {time_range.replace('_', ' ').title()}")

    container_a = grid[1].container()
    container_b = grid[2].container()
    container_c = grid[3].container()
    container_d = grid[4].container()

    with container_a:
        sub_row1 = st.columns(1)
        sub_row2 = st.columns(2)
        mini_grid = [col.container(height=100) for col in sub_row1 + sub_row2]

        total_feedback = stats_data.get("total_feedback", 0)
        positive_feedback = stats_data.get("positive_feedback")
        negative_feedback = stats_data.get("negative_feedback")

        with mini_grid[0]:
            st.metric("Total Feedback", total_feedback)
        with mini_grid[1]:
            st.metric("Positive Feedback", positive_feedback)
        with mini_grid[2]:
            st.metric("Negative Feedback", negative_feedback)

    with container_b:
        sub_row1 = st.columns(2)
        sub_row2 = st.columns(2)
        mini_grid = [col.container(height=100) for col in sub_row1 + sub_row2]

        with mini_grid[0]:
            st.metric("Active Users", stats_data.get("total_active_users", 0))
        with mini_grid[1]:
            st.metric("Total Messages", stats_data.get("total_messages", 0))
        with mini_grid[2]:
            st.metric("Total Sessions", stats_data.get("total_sessions", 0))
        with mini_grid[3]:
            st.metric(
                "Avg Sessions/User",
                f"{stats_data.get('average_sessions_per_user', 0):.1f}",
            )

    with container_c:
        st.write("### Message Distribution (Simulated)")
        # Since we don't have hourly data, create a simulated distribution based on total messages
        total_messages = stats_data.get("total_messages", 0)
        if total_messages > 0:
            # Simulate hourly distribution with some randomness but based on actual total
            base_hourly = total_messages / 24
            y = [
                max(
                    0,
                    int(
                        base_hourly
                        + random.randint(-int(base_hourly / 2), int(base_hourly / 2))
                    ),
                )
                for _ in range(24)
            ]
        else:
            y = [0] * 24

        df = pd.DataFrame({"Messages": y}, index=range(24))
        st.bar_chart(df, x_label="Hour", y_label="Number of Messages")

    with container_d:
        st.write("### User Activity (Simulated)")
        # Simulate user activity based on active users
        active_users = stats_data.get("total_active_users", 0)
        if active_users > 0:
            # Simulate hourly user activity
            base_activity = active_users / 12  # Spread over 12 hours of activity
            y = [
                max(
                    0,
                    int(
                        base_activity
                        + random.randint(
                            -int(base_activity / 3), int(base_activity / 3)
                        )
                    ),
                )
                for _ in range(24)
            ]
        else:
            y = [0] * 24

        df = pd.DataFrame({"Active Users": y}, index=range(24))
        st.line_chart(df, x_label="Hour", y_label="Number of Active Users")


st.set_page_config(page_title="Statistics", layout="wide")

# Create tabs for different time ranges
tab1, tab2, tab3 = st.tabs(["Daily Stats", "Weekly Stats", "Monthly Stats"])

with tab1:
    render_metrics("today")

with tab2:
    render_metrics("this_week")

with tab3:
    render_metrics("this_month")
