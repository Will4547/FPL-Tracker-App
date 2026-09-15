from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# Larger colour palette for bigger FPL leagues
FPL_COLOURS = (
    px.colors.qualitative.Alphabet
    + px.colors.qualitative.Dark24
    + px.colors.qualitative.Light24
)

# Different line styles for additional differentiation
FPL_LINE_STYLES = [
    "solid",
    "dash",
    "dot",
    "dashdot",
    "longdash",
    "longdashdot",
]

# ---------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------

LEAGUE_ID = 206273
BASE_URL = "https://fantasy.premierleague.com/api"

# Refresh cached FPL data every 15 minutes
CACHE_SECONDS = 15 * 60


# ---------------------------------------------------------
# PAGE SETUP
# ---------------------------------------------------------

st.set_page_config(
    page_title="FPL League Tracker",
    page_icon="⚽",
    layout="wide",
)

st.title("⚽ FPL League Tracker")


# ---------------------------------------------------------
# FPL API FUNCTIONS
# ---------------------------------------------------------

def get_json(session, url):
    """Download JSON from the FPL API."""

    response = session.get(
        url,
        timeout=20,
        headers={
            "User-Agent": "FPL-League-Tracker/1.0"
        },
    )

    response.raise_for_status()

    return response.json()


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def load_dashboard(league_id):
    """
    Load league standings and gameweek history.

    This function is cached for 15 minutes so every visitor
    doesn't repeatedly request the FPL API.
    """

    session = requests.Session()

    # -----------------------------------------------------
    # LOAD ALL PAGES OF LEAGUE STANDINGS
    # -----------------------------------------------------

    all_managers = []
    league_info = None

    page = 1

    while True:

        url = (
            f"{BASE_URL}/leagues-classic/"
            f"{league_id}/standings/"
            f"?page_standings={page}"
        )

        data = get_json(session, url)

        if league_info is None:
            league_info = data["league"]

        standings_data = data["standings"]

        all_managers.extend(
            standings_data["results"]
        )

        if not standings_data.get("has_next", False):
            break

        page += 1

        # Safety guard
        if page > 100:
            break

    standings = pd.DataFrame(all_managers)

    if standings.empty:
        raise ValueError(
            "No managers were found in this league."
        )

    # Make sure numeric columns are numeric
    standings["rank"] = pd.to_numeric(
        standings["rank"],
        errors="coerce",
    )

    standings["last_rank"] = pd.to_numeric(
        standings["last_rank"],
        errors="coerce",
    )

    standings["total"] = pd.to_numeric(
        standings["total"],
        errors="coerce",
    )

    # -----------------------------------------------------
    # CREATE DISPLAY NAMES
    # -----------------------------------------------------

    # Usually the team name is enough.
    # If two teams have identical names, add manager name.

    standings["display_name"] = standings["entry_name"]

    duplicate_names = standings[
        "entry_name"
    ].duplicated(keep=False)

    standings.loc[
        duplicate_names,
        "display_name",
    ] = (
        standings.loc[
            duplicate_names,
            "entry_name",
        ]
        + " — "
        + standings.loc[
            duplicate_names,
            "player_name",
        ]
    )

    # -----------------------------------------------------
    # LOAD EACH MANAGER'S GAMEWEEK HISTORY
    # -----------------------------------------------------

    history_rows = []

    for row in standings.itertuples():

        history_url = (
            f"{BASE_URL}/entry/"
            f"{row.entry}/history/"
        )

        history_data = get_json(
            session,
            history_url,
        )

        current_history = history_data.get(
            "current",
            [],
        )

        for gw in current_history:

            history_rows.append(
                {
                    "entry_id": row.entry,
                    "team": row.display_name,
                    "manager": row.player_name,
                    "gameweek": gw["event"],
                    "gameweek_points": gw["points"],
                    "total_points": gw["total_points"],
                    "overall_rank": gw.get(
                        "overall_rank"
                    ),
                }
            )

    history = pd.DataFrame(history_rows)

    fetched_at = datetime.now(
        ZoneInfo("Europe/London")
    )

    return (
        league_info,
        standings,
        history,
        fetched_at,
    )


# ---------------------------------------------------------
# LOAD DATA
# ---------------------------------------------------------

try:

    with st.spinner("Loading FPL league data..."):

        (
            league,
            standings,
            history,
            fetched_at,
        ) = load_dashboard(LEAGUE_ID)

except Exception as error:

    st.error(
        "I couldn't retrieve the FPL league data."
    )

    st.exception(error)

    st.stop()


# ---------------------------------------------------------
# HEADER
# ---------------------------------------------------------

header_left, header_right = st.columns(
    [4, 1]
)

with header_left:

    st.subheader(league["name"])

    st.caption(
        "Last refreshed: "
        + fetched_at.strftime(
            "%d %B %Y at %H:%M"
        )
    )


with header_right:

    if st.button(
        "🔄 Refresh now",
        width="stretch",
    ):

        load_dashboard.clear()

        st.rerun()


# ---------------------------------------------------------
# CURRENT LEAGUE SUMMARY
# ---------------------------------------------------------

standings = standings.sort_values(
    ["total", "rank"],
    ascending=[False, True],
).reset_index(drop=True)

leader_points = standings.iloc[0]["total"]
leader_name = standings.iloc[0]["entry_name"]

if len(standings) > 1:
    second_points = standings.iloc[1]["total"]
    gap_to_second = leader_points - second_points
else:
    gap_to_second = 0


if not history.empty:
    current_gw = int(
        history["gameweek"].max()
    )
else:
    current_gw = 0


col1, col2, col3, col4 = st.columns(4)

with col1:

    st.metric(
        "Gameweek",
        current_gw,
    )


with col2:

    st.metric(
        "League leader",
        leader_name,
        f"{int(leader_points)} points",
    )


with col3:

    st.metric(
        "Lead",
        f"{int(gap_to_second)} pts",
    )


with col4:

    st.metric(
        "Managers",
        len(standings),
    )


st.divider()


# ---------------------------------------------------------
# CURRENT STANDINGS
# ---------------------------------------------------------

st.subheader("Current standings")

table = standings.copy()

table["Behind leader"] = (
    leader_points - table["total"]
)

table["% of leader"] = (
    table["total"]
    / leader_points
    * 100
)

# Rank movement
def rank_movement(row):

    current_rank = row["rank"]
    previous_rank = row["last_rank"]

    if (
        pd.isna(previous_rank)
        or previous_rank == 0
    ):
        return "—"

    change = int(
        previous_rank - current_rank
    )

    if change > 0:
        return f"↑ {change}"

    if change < 0:
        return f"↓ {abs(change)}"

    return "—"


table["Move"] = table.apply(
    rank_movement,
    axis=1,
)

table["% of leader"] = table[
    "% of leader"
].map(
    lambda value: f"{value:.1f}%"
)


table_display = table[
    [
        "rank",
        "entry_name",
        "player_name",
        "total",
        "Behind leader",
        "% of leader",
        "Move",
    ]
].copy()


table_display.columns = [
    "Rank",
    "Team",
    "Manager",
    "Points",
    "Behind",
    "% of leader",
    "Move",
]


st.dataframe(
    table_display,
    hide_index=True,
    width="stretch",
    column_config={
        "Rank": st.column_config.NumberColumn(
            "Rank",
            format="%d",
        ),
        "Points": st.column_config.NumberColumn(
            "Points",
            format="%d",
        ),
        "Behind": st.column_config.NumberColumn(
            "Behind",
            format="%d",
        ),
    },
)


st.divider()


# ---------------------------------------------------------
# HISTORICAL CHART
# ---------------------------------------------------------

st.subheader("League performance over time")


if history.empty:

    st.info(
        "No gameweek history is available yet."
    )

    st.stop()


# Convert history to a wide table:
#
# Gameweek | Team A | Team B | Team C
#
points_by_week = history.pivot(
    index="gameweek",
    columns="team",
    values="total_points",
)

points_by_week = points_by_week.sort_index()


# Leader's cumulative points after each GW
leader_by_week = points_by_week.max(
    axis=1
)


# ---------------------------------------------------------
# CHART CONTROLS
# ---------------------------------------------------------

chart_type = st.radio(
    "View",
    [
        "% of leader",
        "Total points",
        "Points behind leader",
    ],
    horizontal=True,
)


# Order names by current league position
ordered_teams = (
    standings
    .sort_values("rank")
    ["display_name"]
    .tolist()
)


# Avoid an unreadable chart in very large leagues
if len(ordered_teams) <= 15:

    default_teams = ordered_teams

else:

    default_teams = ordered_teams[:15]


selected_teams = st.multiselect(
    "Teams shown",
    options=ordered_teams,
    default=default_teams,
)


if not selected_teams:

    st.warning(
        "Select at least one team to display."
    )

    st.stop()


# ---------------------------------------------------------
# CALCULATE CHART VALUES
# ---------------------------------------------------------

if chart_type == "% of leader":

    chart_data = (
        points_by_week
        .div(
            leader_by_week,
            axis=0,
        )
        * 100
    )

    y_label = "% of leader's points"

    chart_title = (
        "Percentage of League Leader's "
        "Points Over Time"
    )


elif chart_type == "Points behind leader":

    chart_data = points_by_week.apply(
        lambda column:
        leader_by_week - column
    )

    y_label = "Points behind leader"

    chart_title = (
        "Points Behind League Leader "
        "Over Time"
    )


else:

    chart_data = points_by_week.copy()

    y_label = "Total points"

    chart_title = (
        "Cumulative FPL Points Over Time"
    )


chart_data = chart_data[
    selected_teams
]


# Convert to long format for Plotly
plot_data = (
    chart_data
    .reset_index()
    .melt(
        id_vars="gameweek",
        var_name="Team",
        value_name="Value",
    )
)


# ---------------------------------------------------------
# DRAW INTERACTIVE PLOTLY CHART
# ---------------------------------------------------------

fig = px.line(
    plot_data,
    x="gameweek",
    y="Value",
    color="Team",
    markers=True,
    title=chart_title,
    color_discrete_sequence=FPL_COLOURS,
)

# Give each team a different line style as well
for i, team in enumerate(selected_teams):

    fig.update_traces(
        selector={"name": team},
        line={
            "dash": FPL_LINE_STYLES[
                i % len(FPL_LINE_STYLES)
            ],
            "width": 2.5,
        },
        marker={
            "size": 7,
        },
    )



fig.update_layout(
    height=650,
    xaxis_title="Gameweek",
    yaxis_title=y_label,
    hovermode="x unified",
    legend_title_text="Team",
    margin=dict(
        l=20,
        r=20,
        t=60,
        b=20,
    ),
    legend=dict(
        itemclick="toggle",
        itemdoubleclick="toggleothers",
    ),
)


if chart_type == "% of leader":

    fig.add_hline(
        y=100,
        line_dash="dash",
        annotation_text="Leader",
        annotation_position="top left",
    )

    fig.update_yaxes(
        ticksuffix="%"
    )


elif chart_type == "Points behind leader":

    fig.add_hline(
        y=0,
        line_dash="dash",
        annotation_text="Leader",
        annotation_position="top left",
    )


st.plotly_chart(
    fig,
    width="stretch",
)


st.caption(
    "Tip: click a team name in the legend "
    "to hide or show its line. "
    "Double-click a team to isolate it."
)


# ---------------------------------------------------------
# OPTIONAL GAMEWEEK POINTS
# ---------------------------------------------------------

with st.expander(
    "Show gameweek-by-gameweek scores"
):

    gw_scores = history.pivot(
        index="gameweek",
        columns="team",
        values="gameweek_points",
    )

    gw_scores.index.name = "GW"

    st.dataframe(
        gw_scores,
        width="stretch",
    )