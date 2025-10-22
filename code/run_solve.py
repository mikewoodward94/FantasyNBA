import requests
import pandas as pd
import numpy as np
import json
import re
import time

from solver import nba_solver
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

DATA_DIR = PROJECT_ROOT / "data"


def load_settings():
    with open(DATA_DIR / "settings.json") as f:
        options = json.load(f)
    return options


settings = load_settings()

(
    info_source,
    value_cutoff,
    decay,
    home,
    away,
    first_gd,
    first_gw,
    final_gw,
    final_gd,
    locked,
    banned,
    gd_banned,
    ids_to_zero,
    gds_to_zero,
    wildcard,
    allstar,
    day_solve,
    allstar_day,
    gap,
    max_time,
    transfer_penalty,
    team_data,
    team_id,
    ev_sheet,
    gw_cap_used,
) = (
    settings["info_source"],
    settings["value_cutoff"],
    settings["decay"],
    settings["home"],
    settings["away"],
    settings["first_gd"],
    settings["first_gw"],
    settings["final_gw"],
    settings["final_gd"],
    settings["locked"],
    settings["banned"],
    settings["gd_banned"],
    settings["ids_to_zero"],
    settings["gds_to_zero"],
    settings["wildcard"],
    settings["allstar"],
    settings["day_solve"],
    settings["allstar_day"],
    settings["gap"],
    settings["max_time"],
    settings.get("transfer_penalty", {}),
    settings["team_data"],
    settings["team_id"],
    settings["ev_sheet"],
    settings["gw_cap_used"],
)


def main(
    info_source,
    value_cutoff,
    decay,
    home,
    away,
    first_gd,
    first_gw,
    final_gw,
    final_gd,
    locked,
    banned,
    gd_banned,
    ids_to_zero,
    gds_to_zero,
    wildcard,
    allstar,
    day_solve,
    allstar_day,
    gap,
    max_time,
    transfer_penalty,
    ev_sheet,
):
    fixture_file_path = DATA_DIR / "fixtures.csv"
    if info_source == "API":
        # Get From API
        print("Retrieving player and fixture data from Fantasy NBA API")
        player_info = get_player_info()
        player_info.to_csv("../data/player_info.csv", index=False)

        if not fixture_file_path.exists():
            fixture_info = get_fixture_info(player_info)
            fixture_info = clean_fixture_info(fixture_info)
            fixture_info.to_csv("../data/fixtures.csv", index=False)

    in_team, in_team_sell_price, cap_used, transfers_left, in_bank = read_team_json()

    if not ev_sheet:
        print("Generating EV")

        player_info = pd.read_csv("../data/player_info.csv")
        player_info = player_info[
            (player_info["status"].isin(["a", "d"])) | (player_info["id"].isin(in_team))
        ]

        hashtag_data = read_hashtag()

        player_data = player_info.merge(
            hashtag_data, left_on="name", right_on="PLAYER", how="inner"
        )
        player_data = player_data[
            [
                "id",
                "name",
                "team",
                "now_cost",
                "element_type",
                "PTS",
                "TREB",
                "AST",
                "STL",
                "BLK",
                "TO",
                "PPG",
            ]
        ]

        for p_id, selling_price in in_team_sell_price:
            player_data["now_cost"] = np.where(
                player_data["id"] == p_id, selling_price, player_data["now_cost"]
            )

        fixtures = read_fixtures(first_gd, first_gw, final_gw, final_gd)
        player_data = player_data.merge(fixtures, on="id", how="inner")

        team_def_strength = read_team_def_strength()
        team_def_strength.to_csv("../data/team_def_strength.csv", index=False)
        def_rating_dict = team_def_strength.set_index("TEAM").T.to_dict("list")

        location_dict = {"home": home, "away": away}

        player_data = replace_with_value(player_data, location_dict, def_rating_dict)

        print(f"Players before value cutoff: {len(player_data)}")
        player_data["value"] = player_data["PPG"] / player_data["now_cost"]

        player_data = player_data[
            (player_data["value"] >= value_cutoff)
            | (player_data["id"].isin(in_team))
            | (player_data["id"].isin(locked))
        ]
        player_data = player_data.drop(columns=["value"])
        print(f"Players after value cutoff: {len(player_data)}")

        player_data = apply_decay(player_data, decay)

        if allstar:
            if day_solve:
                player_data = player_data[
                    [
                        "id",
                        "name",
                        "team",
                        "now_cost",
                        "element_type",
                        "PTS",
                        "TREB",
                        "AST",
                        "STL",
                        "BLK",
                        "TO",
                        "PPG",
                        allstar_day,
                    ]
                ]
            else:
                player_data = player_data.drop(columns=[allstar_day])

        for gd in gds_to_zero:
            player_data[gd] = np.where(
                player_data["id"].isin(ids_to_zero), 0, player_data[gd]
            )

        player_data.to_csv("../data/NBA_EV.csv", index=False)
        print("EV generated and output to NBA_EV.csv")
    else:
        print("Loading existing EV sheet")
        player_data = pd.read_csv("../data/NBA_EV.csv")

    nba_solver(
        player_data,
        locked,
        banned,
        gd_banned,
        wildcard,
        day_solve,
        in_team,
        cap_used,
        transfers_left,
        in_bank,
        decay,
        gap,
        max_time,
        transfer_penalty,
        first_gw,
        first_gd,
        final_gw,
        final_gd,
    )


def get_player_info():
    url = "https://nbafantasy.nba.com/api/bootstrap-static/"
    r = requests.get(url)
    json = r.json()
    elements = pd.DataFrame(json["elements"])
    elements = elements[
        [
            "id",
            "first_name",
            "second_name",
            "now_cost",
            "team",
            "element_type",
            "status",
        ]
    ]
    elements["name"] = elements["first_name"] + " " + elements["second_name"]

    elements = elements[["id", "name", "now_cost", "team", "element_type", "status"]]
    return elements


def get_fixture_info(player_info):
    fixtures = []

    for i in player_info["id"]:
        url = "https://nbafantasy.nba.com/api/element-summary/" + str(i) + "/"
        r = requests.get(url)
        while r.status_code == 429:
            print("Too many requests, sleeping for 30s")
            time.sleep(30)
            r = requests.get(url)

        json = r.json()
        if json == {"detail": "Not found."}:
            continue
        else:
            data = pd.DataFrame(json["fixtures"])
            data["id"] = i
            data = data[["team_h", "team_a", "event_name", "is_home", "id"]]
            fixtures.append(data)

    fixtures = pd.concat(fixtures)

    return fixtures


def clean_fixture_info(fixture_info):
    fixture_info["opp_team"] = np.where(
        fixture_info["is_home"], fixture_info["team_a"], fixture_info["team_h"]
    )
    fixture_info["location"] = np.where(fixture_info["is_home"], "home", "away")
    fixture_info = fixture_info[["id", "event_name", "location", "opp_team"]]
    fixture_info = fixture_info.dropna()

    return fixture_info


def read_hashtag():
    data = pd.read_csv("../data/hashtag_season.csv")
    data = data[["PLAYER", "PTS", "TREB", "AST", "STL", "BLK", "TO"]]

    data = data[data["PLAYER"] != "PLAYER"]

    cols = ["PTS", "TREB", "AST", "STL", "BLK", "TO"]
    data[cols] = data[cols].apply(pd.to_numeric, errors="coerce")

    multiplier = [1, 1.2, 1.5, 3, 3, -1]
    data[cols] = data[cols] * multiplier
    data["PPG"] = data[cols].sum(axis=1)
    return data


def read_fixtures(first_gd, first_gw, final_gw, final_gd):
    fixtures = pd.read_csv("../Data/fixtures.csv")
    fixtures["gameweek"] = (
        fixtures["event_name"].str.findall("(\d+)").str[0].astype(int)
    )
    fixtures["gameday"] = fixtures["event_name"].str.findall("(\d+)").str[1].astype(int)

    fixtures = fixtures[fixtures["gameweek"] <= final_gw]
    fixtures = fixtures[fixtures["gameweek"] >= first_gw]
    fixtures = fixtures[
        (fixtures["gameweek"] > first_gw) | (fixtures["gameday"] >= first_gd)
    ]
    fixtures = fixtures[
        (fixtures["gameweek"] < final_gw) | (fixtures["gameday"] <= final_gd)
    ]

    fixtures = fixtures[["id", "event_name", "location", "opp_team"]]

    team_ids = pd.read_csv("../data/team_ids.csv")
    fixtures = fixtures.merge(team_ids, left_on="opp_team", right_on="team_id")

    fixtures["info"] = fixtures.apply(lambda x: [x["location"], x["team"]], axis=1)

    fixtures = fixtures[["id", "event_name", "info"]]

    cols = sorted(
        fixtures["event_name"].unique(),
        key=lambda x: (int(x.split()[1]), int(x.split()[-1])),
    )

    fixtures = fixtures.pivot(index="id", columns="event_name", values="info")
    fixtures = fixtures[cols]

    fixtures = fixtures.fillna("").reset_index()

    return fixtures


def read_team_def_strength():
    data = pd.read_csv("../Data/team_def_data_2425.csv")
    data_cols = ["PTS", "REB", "AST", "STL", "BLK", "TOV"]

    for col in data_cols:
        mean = data[col].mean()
        data[f"{col}_rating"] = data[col] / mean

    data = data[
        [
            "TEAM",
            "PTS_rating",
            "REB_rating",
            "AST_rating",
            "STL_rating",
            "BLK_rating",
            "TOV_rating",
        ]
    ]

    return data


def replace_with_value(player_data, location_dict, def_rating_dict):
    game_cols = player_data.columns[12:].to_list()

    for col in game_cols:
        player_data[col] = player_data[col].apply(
            lambda x: replace_values(x, location_dict)
        )
        player_data[col] = player_data[col].apply(
            lambda x: replace_values(x, def_rating_dict)
        )
        player_data[col] = player_data.apply(transform_gameday, axis=1, col=col)
        player_data[col] = player_data[col].apply(multiply_list)

    return player_data


def replace_values(lst, mapping):
    return [mapping.get(item, item) for item in lst]


def transform_gameday(row, col):
    if not row[col]:
        return [0, 0]

    location = row[col][0]
    action_list = row[col][1]
    multiplied_values = [
        action_list[0] * row["PTS"],
        action_list[1] * row["TREB"],
        action_list[2] * row["AST"],
        action_list[3] * row["STL"],
        action_list[4] * row["BLK"],
        action_list[5] * row["TO"],
    ]
    total = sum(multiplied_values)
    return [location, total]


def multiply_list(lst):
    return np.prod(lst)


def apply_decay(player_data, decay_factor):
    week_day_list = []
    week_day_dict = {}

    point_columns = [x for x in player_data.columns if "Gameweek" in x]

    for col in point_columns:
        week = int(re.findall("(\d+)", col)[0])
        day = int(re.findall("(\d+)", col)[1])
        temp_list = [week, day]
        week_day_list.append(temp_list)

    for inner_list in week_day_list:
        key = inner_list[0]
        value = inner_list[1]

        if key not in week_day_dict:
            week_day_dict[key] = []
        week_day_dict[key].append(value)

    decay = 1.0
    for gameweek, gamedays in week_day_dict.items():
        for gameday in gamedays:
            col_name = f"Gameweek {gameweek} - Day {gameday}"
            if col_name in player_data.columns:
                player_data[col_name] *= decay
                player_data[col_name] = round(player_data[col_name], 2)
                decay *= decay_factor
    return player_data


gw_period = [
    {"start_event": 1, "stop_event": 6},
    {"start_event": 7, "stop_event": 13},
    {"start_event": 14, "stop_event": 20},
    {"start_event": 21, "stop_event": 27},
    {"start_event": 28, "stop_event": 34},
    {"start_event": 35, "stop_event": 40},
    {"start_event": 41, "stop_event": 47},
    {"start_event": 48, "stop_event": 51},
    {"start_event": 52, "stop_event": 56},
    {"start_event": 57, "stop_event": 62},
    {"start_event": 63, "stop_event": 69},
    {"start_event": 70, "stop_event": 76},
    {"start_event": 77, "stop_event": 83},
    {"start_event": 84, "stop_event": 90},
    {"start_event": 91, "stop_event": 97},
    {"start_event": 98, "stop_event": 104},
    {"start_event": 105, "stop_event": 108},
    {"start_event": 109, "stop_event": 112},
    {"start_event": 113, "stop_event": 119},
    {"start_event": 120, "stop_event": 126},
    {"start_event": 127, "stop_event": 133},
    {"start_event": 134, "stop_event": 140},
    {"start_event": 141, "stop_event": 147},
    {"start_event": 148, "stop_event": 154},
    {"start_event": 155, "stop_event": 160},
]


def calculate_fts(transfers, next_gd, as_gds, wc_gds, transfer_periods):
    current_period = None
    for period in transfer_periods:
        if period["start_event"] <= next_gd <= period["stop_event"]:
            current_period = period
            break

    if current_period is None:
        return 0

    n_transfers_per_gd = {}
    for t in transfers:
        gd = t["event"]
        if gd and gd < next_gd:
            n_transfers_per_gd[gd] = n_transfers_per_gd.get(gd, 0) + 1

    transfers_used_this_period = 0
    period_start_gd = current_period["start_event"]

    for gd in range(period_start_gd, next_gd):
        if gd in as_gds or gd in wc_gds:
            continue

        transfers_used_this_period += n_transfers_per_gd.get(gd, 0)

    available_fts = 2 - transfers_used_this_period

    return max(0, available_fts)


def read_team_json():
    if team_data == "json":
        with open("../data/team.json") as f:
            d = json.load(f)

            in_team = [pick["element"] for pick in d["picks"]]
            in_team_sell_price = [
                [pick["element"], pick["selling_price"]] for pick in d["picks"]
            ]
            cap_used = any(
                chip["name"] == "phcapt" and chip["status_for_entry"] in ["played"]
                for chip in d["chips"]
            )
            transfers_left = 2 - d["transfers"]["made"]
            in_bank = d["transfers"]["bank"]
    elif team_data == "id":
        BASE_URL = "https://nbafantasy.nba.com/api/"

        with requests.Session() as session:
            static_url = f"{BASE_URL}/bootstrap-static/"
            static = session.get(static_url).json()
            element_to_type_dict = {
                x["id"]: x["element_type"] for x in static["elements"]
            }
            next_gd = next(x for x in static["events"] if x["is_next"])["id"]
            start_prices = {
                x["id"]: x["now_cost"] - x["cost_change_start"]
                for x in static["elements"]
            }
            gd1_url = f"{BASE_URL}/entry/{team_id}/event/1/picks/"
            gd1 = session.get(gd1_url).json()
            transfers_url = f"{BASE_URL}/entry/{team_id}/transfers/"
            transfers = session.get(transfers_url).json()[::-1]
            chips_url = f"{BASE_URL}/entry/{team_id}/history/"
            chips = session.get(chips_url).json()["chips"]
            as_gds = [x["event"] for x in chips if x["name"] == "rich"]
            wc_gds = [x["event"] for x in chips if x["name"] == "wildcard"]
            squad = {x["element"]: start_prices[x["element"]] for x in gd1["picks"]}
            made = gd1["entry_history"]["event_transfers"]
            bank = gd1["entry_history"]["bank"]
            itb = 1000 - sum(squad.values())
            for t in transfers:
                if t["event"] in as_gds:
                    continue
                itb += t["element_out_cost"]
                itb -= t["element_in_cost"]
                if t["element_in"]:
                    squad[t["element_in"]] = t["element_in_cost"]
                if t["element_out"]:
                    del squad[t["element_out"]]
            my_data = {"picks": gd1["picks"], "transfers": {"bank": bank, "made": made}}
            fts = calculate_fts(transfers, next_gd, as_gds, wc_gds, gw_period)
            my_data = {
                "chips": chips,
                "picks": [],
                "team_id": team_id,
                "transfers": {"bank": itb, "limit": fts, "made": 0},
            }
            for player_id, purchase_price in squad.items():
                now_cost = next(x for x in static["elements"] if x["id"] == player_id)[
                    "now_cost"
                ]

                diff = now_cost - purchase_price
                if diff > 0:
                    selling_price = purchase_price + diff // 2
                else:
                    selling_price = now_cost

                my_data["picks"].append(
                    {
                        "element": player_id,
                        "purchase_price": purchase_price,
                        "selling_price": selling_price,
                        "element_type": element_to_type_dict[player_id],
                    }
                )

        in_team = [pick["element"] for pick in my_data["picks"]]
        in_team_sell_price = [
            [pick["element"], pick["selling_price"]] for pick in my_data["picks"]
        ]
        cap_used = gw_cap_used
        transfers_left = 2 - my_data["transfers"]["made"]
        in_bank = my_data["transfers"]["bank"]

    return (in_team, in_team_sell_price, cap_used, transfers_left, in_bank)


if __name__ == "__main__":
    main(
        info_source,
        value_cutoff,
        decay,
        home,
        away,
        first_gd,
        first_gw,
        final_gw,
        final_gd,
        locked,
        banned,
        gd_banned,
        ids_to_zero,
        gds_to_zero,
        wildcard,
        allstar,
        day_solve,
        allstar_day,
        gap,
        max_time,
        transfer_penalty,
        ev_sheet,
    )
