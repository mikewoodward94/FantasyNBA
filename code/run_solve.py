import requests
import pandas as pd
import numpy as np
import json
import re
import time
import datetime
from tabulate import tabulate  # type: ignore

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
    use_wc,
    use_as,
    booked_transfers,
    chip_limits,
    num_iterations,
    iteration_criteria,
    iteration_difference,
    day_solve,
    gap,
    max_time,
    transfer_penalty,
    hit_cost,
    weekly_hit_limit,
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
    settings.get("use_wc", []),
    settings.get("use_as", []),
    settings.get("booked_transfers", []),
    settings.get("chip_limits", {}),
    settings.get("num_iterations", 1),
    settings.get("iteration_criteria", "this_day_transfer_in_out"),
    settings.get("iteration_difference", 1),
    settings["day_solve"],
    settings["gap"],
    settings["max_time"],
    settings.get("transfer_penalty", {}),
    settings.get("hit_cost", 100),
    settings.get("weekly_hit_limit"),
    settings["team_data"],
    settings["team_id"],
    settings["ev_sheet"],
    settings["gw_cap_used"],
)


def print_transfer_chip_summary(result):
    print(f"\nSolution {result['iter']} (Score: {result['score']:.2f})")

    full_player_df = result["full_player_df"]
    wildcard = result["use_wc"]
    allstar = result["use_as"]

    squad_day_cols = [col for col in full_player_df.columns if col.startswith("squad_")]
    squad_day_cols.sort(key=lambda x: (int(x.split("_")[1]), int(x.split("_")[2])))

    squad_day_cols.insert(0, "current")

    true_prev_col = "current"

    for i in range(1, len(squad_day_cols)):
        curr_col = squad_day_cols[i]
        day_str = curr_col.replace("squad_", "")
        week, day = day_str.split("_")
        line_text = f"Gameweek {week} - Day {day}: "

        # Check for chips
        is_as_day = day_str in allstar
        chip_text = ""
        if day_str in wildcard:
            chip_text = "Wildcard"
        elif is_as_day:
            chip_text = "All-Star"

        if chip_text:
            line_text += f"({chip_text}) "

        temp_sells = []
        temp_buys = []

        # anly calculate transfers if its not an allstar day
        if not is_as_day:
            for _, row in full_player_df.iterrows():
                if row[true_prev_col] != row[curr_col]:
                    if row[true_prev_col] == 1:
                        temp_sells.append(row["name"])
                    else:
                        temp_buys.append(row["name"])

        sell_text = ", ".join(temp_sells)
        buy_text = ", ".join(temp_buys)

        if sell_text or buy_text:
            line_text += f"{sell_text} -> {buy_text}"
        elif not chip_text:
            line_text += "Roll"

        print(f"\t{line_text}")

        if not is_as_day:
            true_prev_col = curr_col


def print_squad_lineups(result, initial_in_bank, initial_transfers_left, hit_cost):
    print(f"\n\n======= Squad Lineups for Iteration {result['iter']} =======")

    full_player_df = result["full_player_df"]
    combined_df = result["picks_df"]
    wildcard = result["use_wc"]
    allstar = result["use_as"]

    current_itb = initial_in_bank
    current_loop_week = -1
    week_ft_remaining = 0

    squad_day_cols = [col for col in full_player_df.columns if col.startswith("squad_")]
    squad_day_cols.sort(key=lambda x: (int(x.split("_")[1]), int(x.split("_")[2])))

    squad_day_cols.insert(0, "current")

    true_prev_col = "current"
    total_calculated_xpts = 0.0

    current_itb = initial_in_bank / 10
    current_loop_week = -1
    week_ft_remaining = 0

    for i in range(1, len(squad_day_cols)):
        curr_col = squad_day_cols[i]
        current_day_str = curr_col.replace("squad_", "")
        a, b = current_day_str.split("_")
        a_int = int(a)

        is_as_day = current_day_str in allstar
        is_wc_day = current_day_str in wildcard

        chip_played_str = ""
        if is_wc_day:
            chip_played_str = " (Wildcard)"
        elif is_as_day:
            chip_played_str = " (All-Star)"

        temp_sells = []
        temp_buys = []
        cost_of_sells = 0
        cost_of_buys = 0

        for _, row in full_player_df.iterrows():
            if row[true_prev_col] != row[curr_col]:
                if row[true_prev_col] == 1:
                    temp_sells.append(f"Sell {row['id']} - {row['name']}")
                    cost_of_sells += row["now_cost"] / 10
                else:
                    temp_buys.append(f"Buy {row['id']} - {row['name']}")
                    cost_of_buys += row["now_cost"] / 10

        nt_this_day = len(temp_buys)

        is_new_week = a_int != current_loop_week

        if is_new_week:
            current_loop_week = a_int
            week_ft_remaining = (
                initial_transfers_left if a_int == result["current_week"] else 2
            )

            hits_dict = result.get("hits", {})
            hits_this_week = hits_dict.get(a_int, 0)
            pt_this_day = hits_this_week * hit_cost
        else:
            pt_this_day = 0

        hit_msg = ""
        if pt_this_day > 0:
            hit_msg = f" (Hit: -{pt_this_day})"

        print(f"Gameweek {a} - Day {b}{chip_played_str}{hit_msg} : ")

        itb_before_this_day = current_itb

        itb_after_this_day = itb_before_this_day + cost_of_sells - cost_of_buys

        ft_this_day_str = str(week_ft_remaining)

        if not (is_as_day or is_wc_day):
            week_ft_remaining = max(0, week_ft_remaining - nt_this_day)
        else:
            ft_this_day_str = "∞"

        if is_as_day:
            print(
                f"\tITB= ∞ -> ∞, FT= {ft_this_day_str}, PT={pt_this_day}, NT={nt_this_day}"
            )
        else:
            print(
                f"\tITB={itb_before_this_day:.1f}->{itb_after_this_day:.1f}, FT={ft_this_day_str}, PT={pt_this_day}, NT={nt_this_day}"
            )

        if temp_sells:
            for s in temp_sells:
                print(f"\t{s}")
        if temp_buys:
            for buy_str in temp_buys:
                print(f"\t{buy_str}")

        current_itb = itb_after_this_day
        if not is_as_day:
            true_prev_col = curr_col

        print("Line-up: ")
        front_court = []
        back_court = []
        bench_list = []
        day_xPts = 0.0

        for _, row in combined_df.iterrows():
            day_str = f"{a}_{b}"
            team_col = f"team_{day_str}"
            squad_col = f"squad_{day_str}"
            cap_col = f"cap_{day_str}"
            xpts_col = f"xPts_{day_str}"

            if row[squad_col] == 1:
                player_xpts = row.get(xpts_col, 0.0)
                player_name = f"{row['name']}({player_xpts:.2f})"
                if row[cap_col] == 1:
                    player_name += " (C)"

                if row[team_col] == 1:
                    if row["element_type"] == 2:
                        front_court.append(player_name)
                    else:
                        back_court.append(player_name)

                    if row[cap_col] == 1 and not is_as_day:
                        day_xPts += player_xpts * 2
                    else:
                        day_xPts += player_xpts
                else:
                    bench_list.append((player_xpts, player_name))

        print("\t" + ", ".join(front_court))
        print("\t" + ", ".join(back_court) + "\n")

        bench_list.sort(key=lambda x: x[0], reverse=True)
        bench_names = [name for xpts, name in bench_list]

        print("Benched: \n " + "\t" + ", ".join(bench_names))

        final_day_score = day_xPts - pt_this_day
        print(f"Total xPts: {final_day_score:.2f}\n")
        total_calculated_xpts += final_day_score

    print("\n")
    print(f"Total xPts across the horizon: {total_calculated_xpts:.2f}\n")


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
    use_wc,
    use_as,
    booked_transfers,
    num_iterations,
    iteration_criteria,
    iteration_difference,
    day_solve,
    gap,
    max_time,
    transfer_penalty,
    hit_cost,
    weekly_hit_limit,
    ev_sheet,
):
    fixture_file_path = DATA_DIR / "fixtures.csv"
    if info_source == "API":
        print("Retrieving player and fixture data from Fantasy NBA API")
        player_info = get_player_info()
        player_info.to_csv("../data/player_info.csv", index=False)

        if not fixture_file_path.exists():
            fixture_info = get_fixture_info(player_info)
            fixture_info = clean_fixture_info(fixture_info)
            fixture_info.to_csv("../data/fixtures.csv", index=False)

    in_team, in_team_sell_price, cap_used, transfers_left, in_bank, current_api_gw = (
        read_team_json()
    )

    effective_transfers_left = transfers_left
    if first_gw > current_api_gw:
        effective_transfers_left = 2

    if not ev_sheet:
        print("Generating EV")
        player_info = pd.read_csv("../data/player_info.csv")
        player_info = player_info[
            (player_info["status"].isin(["a", "d"])) | (player_info["id"].isin(in_team))
        ]
        hashtag_data = read_hashtag()
        name_fixes = {
            "Walter Clayton": "Walter Clayton Jr.",
            "Gary Trent": "Gary Trent Jr.",
            "A.J. Johnson": "AJ Johnson",
            "O.G. Anunoby": "OG Anunoby",
            "Yanic Konan Niederhauser": "Yanic Konan Niederhäuser",
            "Robert Williams": "Robert Williams III",
            "PJ Washington": "P.J. Washington",
            "R.J. Barrett": "RJ Barrett",
            "Kevin McCullar Jr": "Kevin McCullar Jr.",
            "Trey Murphy": "Trey Murphy III",
            "Craig Porter Jr.": "Craig Porter",
            "Derrick Jones": "Derrick Jones Jr.",
            "KJ Simpson": "K.J. Simpson",
            "Patrick Baldwin": "Patrick Baldwin Jr.",
            "J.D. Davison": "JD Davison",
            "Chris Manon": "Chris Mañon",
            "Egor Demin": "Egor Dëmin",
            "Kelly Oubre": "Kelly Oubre Jr.",
            "AJ Green": "A.J. Green",
            "Wendell Moore Jr": "Wendell Moore Jr.",
            "Hugo Gonzalez": "Hugo González",
            "David Duke": "David Duke Jr.",
            "G.G. Jackson": "GG Jackson",
            "C.J. McCollum": "CJ McCollum",
            "Jeenathan Williams Jr.": "Jeenathan Williams",
            "Cam Johnson": "Cameron Johnson",
            "Ron Holland": "Ronald Holland II",
            "Nicolas Claxton": "Nic Claxton",
            "Herb Jones": "Herbert Jones",
            "Bub Carrington": "Carlton Carrington",
            "David Jones-Garcia": "David Jones",
            "Mouhamadou Gueye": "Mouhamed Gueye",
            "EJ Harkless": "Elijah Harkless",
        }
        hashtag_data["PLAYER"] = hashtag_data["PLAYER"].replace(name_fixes)
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

        for gd in gds_to_zero:
            player_data[gd] = np.where(
                player_data["id"].isin(ids_to_zero), 0, player_data[gd]
            )
        player_data.to_csv("../data/NBA_EV.csv", index=False)
        print("EV generated and output to NBA_EV.csv")
    elif ev_sheet == "mou":
        player_data = pd.read_csv("../data/mou.csv")
        pt_cols = [c for c in player_data.columns if c.startswith("Gameweek")]

        player_data["ev_across"] = (
            player_data[pt_cols].replace(0, np.nan).mean(axis=1).fillna(0)
        )

        player_data["value"] = player_data["ev_across"] / player_data["now_cost"]

        print(f"Players before value cutoff: {len(player_data)}")
        player_data = player_data[
            (player_data["value"] >= value_cutoff)
            | (player_data["id"].isin(in_team))
            | (player_data["id"].isin(locked))
        ]
        print(f"Players after value cutoff: {len(player_data)}")

        player_data = player_data.drop(columns=["ev_across", "value"])
    else:
        print("Loading existing EV sheet")
        player_data = pd.read_csv("../data/NBA_EV.csv")

    response = nba_solver(
        player_data,
        locked,
        banned,
        gd_banned,
        use_wc,
        use_as,
        booked_transfers,
        day_solve,
        in_team,
        cap_used,
        effective_transfers_left,
        in_bank,
        decay,
        gap,
        max_time,
        transfer_penalty,
        hit_cost,
        weekly_hit_limit,
        first_gw,
        first_gd,
        final_gw,
        final_gd,
        current_api_gw,
        iteration=0,
        iteration_criteria=iteration_criteria,
        iteration_difference=iteration_difference,
        num_iterations=num_iterations,
    )

    run_id = f"{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{np.random.randint(10000, 99999)}"

    for res in response:
        res["run_id"] = f"{run_id}_iter{res['iter']}"

        if settings.get("export_excel", True):
            output_dir = PROJECT_ROOT / "output"
            if not output_dir.exists():
                output_dir.mkdir(parents=True)

            filename = f"NBA_Squad_{res['run_id']}.xlsx"

            try:
                writer = pd.ExcelWriter(output_dir / filename, engine="xlsxwriter")
                res["picks_df"].to_excel(writer, sheet_name="Team_Plan", index=False)
                writer.close()
                print(f"Squad and Transfer Plan output to output/{filename}")
            except Exception as e:
                print(f"Error saving Excel file: {e}")

        if settings.get("print_squads", True):
            print_squad_lineups(res, in_bank, effective_transfers_left, hit_cost)

    if settings.get("print_transfer_chip_summary", True):
        print("\n\n\nTransfer Overview")
        for res in response:
            print_transfer_chip_summary(res)

    if settings.get("print_result_table", True):
        print(f"\n\nResult{'s' if len(response) > 1 else ''}")

        result_table_data = []
        for res in sorted(response, key=lambda x: x["score"], reverse=True):
            result_table_data.append(
                [
                    res["iter"],
                    res["sell"],
                    res["buy"],
                    res["chip"],
                    f"{res['score']:.2f}",
                ]
            )

        print(
            tabulate(
                result_table_data,
                headers=["iter", "sell", "buy", "chip", "score"],
                tablefmt="pipe",
            )
        )
        print("\n\n")

    return response


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
    {"start_event": 48, "stop_event": 54},
    {"start_event": 55, "stop_event": 60},
    {"start_event": 61, "stop_event": 66},
    {"start_event": 67, "stop_event": 73},
    {"start_event": 74, "stop_event": 80},
    {"start_event": 81, "stop_event": 87},
    {"start_event": 88, "stop_event": 94},
    {"start_event": 95, "stop_event": 101},
    {"start_event": 102, "stop_event": 108},
    {"start_event": 109, "stop_event": 112},
    {"start_event": 113, "stop_event": 116},
    {"start_event": 117, "stop_event": 123},
    {"start_event": 124, "stop_event": 130},
    {"start_event": 131, "stop_event": 137},
    {"start_event": 138, "stop_event": 144},
    {"start_event": 145, "stop_event": 151},
    {"start_event": 152, "stop_event": 158},
    {"start_event": 159, "stop_event": 164},
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
    current_gw = first_gw

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
            transfers_left = max(0, 2 - d["transfers"]["made"])
            in_bank = d["transfers"]["bank"]
            if "current_event" in d:
                current_gw = d["current_event"]

    elif team_data == "id":
        BASE_URL = "https://nbafantasy.nba.com/api/"
        with requests.Session() as session:
            static_url = f"{BASE_URL}/bootstrap-static/"
            static = session.get(static_url).json()

            current_event_obj = next(
                (x for x in static["events"] if x["is_current"]), None
            )
            if current_event_obj:
                current_gw = current_event_obj["id"]
            else:
                next_event = next((x for x in static["events"] if x["is_next"]), None)
                current_gw = next_event["id"] - 1 if next_event else 1

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
            if gd1 == {"detail": "Not found."}:
                gd1_url = f"{BASE_URL}/entry/{team_id}/event/2/picks/"
                gd1 = session.get(gd1_url).json()
            else:
                pass
            transfers_url = f"{BASE_URL}/entry/{team_id}/transfers/"
            transfers = session.get(transfers_url).json()[::-1]
            chips_url = f"{BASE_URL}/entry/{team_id}/history/"
            chips = session.get(chips_url).json()["chips"]
            as_gds = [x["event"] for x in chips if x["name"] == "rich"]
            wc_gds = [x["event"] for x in chips if x["name"] == "wildcard"]
            squad = {x["element"]: start_prices[x["element"]] for x in gd1["picks"]}
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
            fts = calculate_fts(transfers, next_gd, as_gds, wc_gds, gw_period)
            made = 2 - fts
            my_data = {
                "chips": chips,
                "picks": [],
                "team_id": team_id,
                "transfers": {"bank": itb, "limit": 2, "made": made},
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
        transfers_left = max(0, 2 - my_data["transfers"]["made"])
        in_bank = my_data["transfers"]["bank"]

    return (in_team, in_team_sell_price, cap_used, transfers_left, in_bank, current_gw)


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
        use_wc,
        use_as,
        booked_transfers,
        num_iterations,
        iteration_criteria,
        iteration_difference,
        day_solve,
        gap,
        max_time,
        transfer_penalty,
        hit_cost,
        weekly_hit_limit,
        ev_sheet,
    )
