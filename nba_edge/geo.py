"""Arena locations, time zones and altitude for travel / altitude factors."""
import math
from zoneinfo import ZoneInfo

# ESPN abbreviation -> (lat, lon, IANA time zone, altitude in feet)
ARENAS = {
    "ATL": (33.757, -84.396, "America/New_York", 1050),
    "BOS": (42.366, -71.062, "America/New_York", 20),
    "BKN": (40.683, -73.976, "America/New_York", 30),
    "CHA": (35.225, -80.839, "America/New_York", 750),
    "CHI": (41.881, -87.674, "America/Chicago", 600),
    "CLE": (41.496, -81.688, "America/New_York", 650),
    "DAL": (32.790, -96.810, "America/Chicago", 430),
    "DEN": (39.749, -105.008, "America/Denver", 5280),
    "DET": (42.341, -83.055, "America/Detroit", 600),
    "GS": (37.768, -122.388, "America/Los_Angeles", 10),
    "HOU": (29.751, -95.362, "America/Chicago", 50),
    "IND": (39.764, -86.156, "America/Indiana/Indianapolis", 715),
    "LAC": (33.945, -118.341, "America/Los_Angeles", 100),
    "LAL": (34.043, -118.267, "America/Los_Angeles", 270),
    "MEM": (35.138, -90.051, "America/Chicago", 260),
    "MIA": (25.781, -80.188, "America/New_York", 10),
    "MIL": (43.045, -87.917, "America/Chicago", 600),
    "MIN": (44.979, -93.276, "America/Chicago", 830),
    "NO": (29.949, -90.082, "America/Chicago", 10),
    "NY": (40.751, -73.993, "America/New_York", 30),
    "OKC": (35.463, -97.515, "America/Chicago", 1200),
    "ORL": (28.539, -81.384, "America/New_York", 100),
    "PHI": (39.901, -75.172, "America/New_York", 30),
    "PHX": (33.446, -112.071, "America/Phoenix", 1100),
    "POR": (45.532, -122.667, "America/Los_Angeles", 50),
    "SAC": (38.580, -121.500, "America/Los_Angeles", 30),
    "SA": (29.427, -98.437, "America/Chicago", 650),
    "TOR": (43.643, -79.379, "America/Toronto", 250),
    "UTAH": (40.768, -111.901, "America/Denver", 4226),
    "WSH": (38.898, -77.021, "America/New_York", 50),
}

TEAM_NAMES = {
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GS": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NO": "New Orleans Pelicans", "NY": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SA": "San Antonio Spurs",
    "TOR": "Toronto Raptors", "UTAH": "Utah Jazz", "WSH": "Washington Wizards",
}

_ALIASES = {"GSW": "GS", "NYK": "NY", "NOP": "NO", "SAS": "SA", "UTA": "UTAH",
            "WAS": "WSH", "PHO": "PHX", "BRK": "BKN", "CHO": "CHA", "NJN": "BKN"}


def canon_abbr(a):
    a = (a or "").upper().strip()
    return _ALIASES.get(a, a)


def is_altitude(team):
    return ARENAS.get(team, (0, 0, "", 0))[3] >= 4000


def km_between(a, b):
    if a not in ARENAS or b not in ARENAS or a == b:
        return 0.0
    lat1, lon1 = map(math.radians, ARENAS[a][:2])
    lat2, lon2 = map(math.radians, ARENAS[b][:2])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def tz_shift_hours(a, b, when):
    """Absolute UTC-offset difference between two arenas at a moment in time."""
    if a not in ARENAS or b not in ARENAS:
        return 0.0
    oa = when.astimezone(ZoneInfo(ARENAS[a][2])).utcoffset().total_seconds()
    ob = when.astimezone(ZoneInfo(ARENAS[b][2])).utcoffset().total_seconds()
    return abs(oa - ob) / 3600

# Team colours (primary, secondary) used for badges and bars on the site.
TEAM_COLORS = {
    "ATL": ("#E03A3E", "#26282A"), "BOS": ("#007A33", "#BA9653"), "BKN": ("#111111", "#777D84"),
    "CHA": ("#1D1160", "#00788C"), "CHI": ("#CE1141", "#000000"), "CLE": ("#860038", "#FDBB30"),
    "DAL": ("#00538C", "#B8C4CA"), "DEN": ("#0E2240", "#FEC524"), "DET": ("#C8102E", "#1D42BA"),
    "GS": ("#1D428A", "#FFC72C"), "HOU": ("#CE1141", "#000000"), "IND": ("#002D62", "#FDBB30"),
    "LAC": ("#C8102E", "#1D428A"), "LAL": ("#552583", "#FDB927"), "MEM": ("#5D76A9", "#12173F"),
    "MIA": ("#98002E", "#F9A01B"), "MIL": ("#00471B", "#EEE1C6"), "MIN": ("#0C2340", "#78BE20"),
    "NO": ("#0C2340", "#C8102E"), "NY": ("#006BB6", "#F58426"), "OKC": ("#007AC1", "#EF3B24"),
    "ORL": ("#0077C0", "#C4CED4"), "PHI": ("#006BB6", "#ED174C"), "PHX": ("#1D1160", "#E56020"),
    "POR": ("#E03A3E", "#000000"), "SAC": ("#5A2D81", "#63727A"), "SA": ("#1F1F1F", "#C4CED4"),
    "TOR": ("#CE1141", "#000000"), "UTAH": ("#3E2680", "#79A3DC"), "WSH": ("#002B5C", "#E31837"),
}
