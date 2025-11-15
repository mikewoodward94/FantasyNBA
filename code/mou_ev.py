# -*- coding: utf-8 -*-
"""
Created on Fri Oct 17 15:52:26 2025
NBA Projections based on data from Dunks and Threes EPM
@author: Subramanya.Ganti
"""

# %% imports
import pandas as pd

import requests
from bs4 import BeautifulSoup
import re
import ast
import urllib3
from pathlib import Path

root = Path(__file__).parent.parent
output_dir = root / "data"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

pd.set_option("mode.chained_assignment", None)

gws_to_run = [4, 5, 6]  # Just set to any GW(s), it should handle the days automatically


# %% functions
def get_player_info():
    url = "https://nbafantasy.nba.com/api/bootstrap-static/"
    r = requests.get(url, verify=False)
    json = r.json()
    elements = pd.DataFrame(json["elements"])
    elements["name"] = elements["first_name"] + " " + elements["second_name"]
    teams = pd.DataFrame(json["teams"])

    elements = elements[["code", "id", "name", "now_cost", "team", "element_type"]]
    teams = teams[["id", "name", "short_name"]]
    return (elements, teams)


def get_fixture_info(player_info):
    fixtures = []

    for i in player_info["id"]:
        url = "https://nbafantasy.nba.com/api/element-summary/" + str(i) + "/"
        r = requests.get(url, verify=False)
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


def extract_epm_data():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    url = "https://dunksandthrees.com/epm"

    try:
        response = requests.get(url, verify=False, headers=headers)
        response.raise_for_status()  # Raise an exception for bad status codes
    except requests.exceptions.RequestException as e:
        print(f"Error fetching the URL: {e}")

    data = response.text
    soup = BeautifulSoup(data, "html.parser")
    script_tags = soup.find_all("script")
    script_contents = []

    for script in script_tags:
        if script.string:  # Check if the script tag has content
            script_contents.append(script.string.strip())

    pattern = r"\{season:2026,game_dt.*?\}"
    matches = re.findall(pattern, data)
    data_list = [match.strip() for match in matches]
    return data_list


def modify_strings(list_of_s):
    mod_list = []
    for s in list_of_s:
        s = s.replace(",", "," + '"')
        s = s.replace(":", '"' + ":")
        s = s.replace("{", '{"')
        s = s.replace("null", "0")
        mod_list.append(s)
    return mod_list


def convert_string_list_to_dict(string_list):
    """
    Converts a list of strings, each representing a dictionary-like structure,
    into a list of actual Python dictionaries.
    """
    result_dicts = []
    for s in string_list:
        try:
            # Safely evaluate the string as a Python literal (dictionary)
            evaluated_dict = ast.literal_eval(s)
            if isinstance(evaluated_dict, dict):
                result_dicts.append(evaluated_dict)
            else:
                print(f"Warning: '{s}' did not evaluate to a dictionary.")
        except (ValueError, SyntaxError) as e:
            print(f"Error evaluating string '{s}': {e}")
    return result_dicts


def mins_adjustment(full):
    adjusted = []
    full["p_mp_48"] *= 1.1
    for t in full["team_alias"].unique():
        outfielders = full[full["team_alias"] == t]
        outfielders = outfielders.sort_values(by="p_mp_48", ascending=False)
        outfielders["rank"] = list(range(1, len(outfielders) + 1))
        outfielders.loc[outfielders["rank"] > 13, "p_mp_48"] = 0
        exp = 1.0
        while (outfielders["p_mp_48"].sum() <= 235) or (
            outfielders["p_mp_48"].sum() >= 245
        ):
            # print(outfielders['p_mp_48'].sum())
            if outfielders["p_mp_48"].sum() <= 235:
                outfielders["p_mp_48"] *= pow(exp, outfielders["rank"] / 2)
                exp += 0.001
            elif outfielders["p_mp_48"].sum() >= 245:
                outfielders["p_mp_48"] *= pow(exp, outfielders["rank"] / 2)
                exp -= 0.001
            outfielders["p_mp_48"] = outfielders["p_mp_48"].clip(upper=48)
        outfielders["p_mp_48"] = (
            240 * outfielders["p_mp_48"] / outfielders["p_mp_48"].sum()
        )
        adjusted.append(outfielders)
    adjusted = pd.concat(adjusted)
    return adjusted


def injury_status():
    injuries = pd.read_html("https://sports.yahoo.com/nba/injuries/")
    injuries = pd.concat(injuries)
    injuries = injuries[["Player", "Pos", "Status", "Date"]]
    injuries = injuries.dropna()
    injuries["Player"] = injuries["Player"].str.replace("í", "i")
    injuries["Player"] = injuries["Player"].str.replace("č", "c")
    injuries["Player"] = injuries["Player"].str.replace("Č", "C")
    injuries["Player"] = injuries["Player"].str.replace("ić", "ic")
    injuries["Player"] = injuries["Player"].str.replace("ö", "o")
    injuries["Player"] = injuries["Player"].str.replace("é", "e")
    injuries["Player"] = injuries["Player"].str.replace("ü", "u")
    injuries["Player"] = injuries["Player"].str.replace("ņ", "n")
    injuries["Player"] = injuries["Player"].str.replace("ģ", "g")
    injuries["Player"] = injuries["Player"].str.replace("ô", "o")
    injuries["Player"] = injuries["Player"].str.replace("ū", "u")
    injuries["Player"] = injuries["Player"].str.replace("Ş", "S")
    injuries["Player"] = injuries["Player"].str.replace("Š", "S")
    injuries["Player"] = injuries["Player"].str.replace("è", "e")
    # injuries['Player'] = injuries['Player'].str.replace('P.J. Washington Jr.','P.J. Washington')
    # injuries['Player'] = injuries['Player'].str.replace('GG Jackson II','GG Jackson')
    # injuries['Player'] = injuries['Player'].str.replace('Xavier Tillman Sr.','Xavier Tillman')
    # injuries['Player'] = injuries['Player'].str.replace('Jeff Dowtin Jr.','Jeff Dowtin')
    # injuries['Player'] = injuries['Player'].str.replace('Craig Porter Jr.','Craig Porter')
    # injuries['Player'] = injuries['Player'].str.replace('Ron Holland II','Ronald Holland II')
    # injuries['Player'] = injuries['Player'].str.replace('Tolu Smith III','Tolu Smith')
    # injuries['Player'] = injuries['Player'].str.replace('Trey Jemison III','Trey Jemison')
    # injuries['Player'] = injuries['Player'].str.replace('AJ Green','A.J. Green')
    # injuries['Player'] = injuries['Player'].str.replace('KJ Simpson','K.J. Simpson')
    # injuries['Player'] = injuries['Player'].str.replace('KJ Martin','Kenyon Martin Jr.')
    return injuries


def matchup_stats(home, away, matchup, team):
    # print()
    game_pace = (
        matchup.loc[matchup["team_alias"] == home, "adj_pace"].values[0]
        + matchup.loc[matchup["team_alias"] == away, "adj_pace"].values[0]
    ) / 2
    """
    playoffs = 0
    league_avg_stats = pd.read_html('https://www.basketball-reference.com/leagues/NBA_stats_per_game.html')
    if(playoffs == 1): c_season = league_avg_stats[1]
    else: c_season = league_avg_stats[0]
    c_season.columns = c_season.columns.droplevel(0)
    c_season = c_season.dropna()
    c_season = c_season.loc[c_season['Rk']!='Rk']
    #c_season = c_season.apply(pd.to_numeric,errors='ignore') #deprecated
    c_season = c_season.apply(lambda x: pd.to_numeric(x, errors='ignore'))
    c_season['weight'] = np.exp(-c_season['Rk']) * c_season['G']
    league_pace = sum(c_season['weight']*c_season['Pace'])/sum(c_season['weight'])
    #league_avg_ortg = sum(c_season['weight']*c_season['ORtg'])/sum(c_season['weight'])
    """
    game_pace *= (
        99 / matchup["adj_pace"].mean()
    )  # 99 for regular season, 95 for the playoffs

    home_pace_factor = (
        game_pace / matchup.loc[matchup["team_alias"] == home, "adj_pace"].values[0]
    )
    away_pace_factor = (
        game_pace / matchup.loc[matchup["team_alias"] == away, "adj_pace"].values[0]
    )

    # team = df_adj.copy()
    team = team[(team["team_alias"] == home) | (team["team_alias"] == away)]
    team.loc[team["team_alias"] == home, "pace factor"] = home_pace_factor
    team.loc[team["team_alias"] == away, "pace factor"] = away_pace_factor

    home_usage = (
        team.loc[team["team_alias"] == home, "p_usg"]
        * team.loc[team["team_alias"] == home, "p_mp_48"]
        / 48
    ).sum()
    team.loc[team["team_alias"] == home, "factor"] = 1 / home_usage
    away_usage = (
        team.loc[team["team_alias"] == away, "p_usg"]
        * team.loc[team["team_alias"] == away, "p_mp_48"]
        / 48
    ).sum()
    team.loc[team["team_alias"] == away, "factor"] = 1 / away_usage

    team["pts"] = (
        team["p_pts_100"]
        * (team["p_t_poss_48"] / 100)
        * (team["p_mp_48"] / 48)
        * team["factor"]
        * team["pace factor"]
    )
    team["ast"] = (
        team["p_ast_100"]
        * (team["p_t_poss_48"] / 100)
        * (team["p_mp_48"] / 48)
        * team["factor"]
        * team["pace factor"]
    )
    team["tov"] = (
        team["p_tov_100"]
        * (team["p_t_poss_48"] / 100)
        * (team["p_mp_48"] / 48)
        * team["factor"]
        * team["pace factor"]
    )
    team["orb"] = (
        team["p_orb_100"]
        * (team["p_t_poss_48"] / 100)
        * (team["p_mp_48"] / 48)
        * team["factor"]
        * team["pace factor"]
    )
    team["drb"] = (
        team["p_drb_100"]
        * (team["p_t_poss_48"] / 100)
        * (team["p_mp_48"] / 48)
        * team["factor"]
        * team["pace factor"]
    )
    team["stl"] = (
        team["p_stl_100"]
        * (team["p_t_poss_48"] / 100)
        * (team["p_mp_48"] / 48)
        * team["factor"]
        * team["pace factor"]
    )
    team["blk"] = (
        team["p_blk_100"]
        * (team["p_t_poss_48"] / 100)
        * (team["p_mp_48"] / 48)
        * team["factor"]
        * team["pace factor"]
    )

    rating_adj = (
        matchup.loc[matchup["team_alias"] == home, "rating"].values[0]
        - matchup.loc[matchup["team_alias"] == away, "rating"].values[0]
        + 2.5
    )
    home_pts = team.loc[team["team_alias"] == home, "pts"].sum()
    away_pts = team.loc[team["team_alias"] == away, "pts"].sum()
    home_adj = (home_pts + (rating_adj - (home_pts - away_pts)) / 2) / home_pts
    away_adj = (away_pts - (rating_adj - (home_pts - away_pts)) / 2) / away_pts

    team.loc[team["team_alias"] == home, "pts"] *= home_adj
    team.loc[team["team_alias"] == home, "ast"] *= home_adj
    team.loc[team["team_alias"] == home, "tov"] *= home_adj
    team.loc[team["team_alias"] == home, "orb"] *= home_adj
    team.loc[team["team_alias"] == home, "drb"] *= home_adj
    team.loc[team["team_alias"] == home, "stl"] *= home_adj
    team.loc[team["team_alias"] == home, "blk"] *= home_adj
    team.loc[team["team_alias"] == home, "opponent"] = away
    team.loc[team["team_alias"] == away, "pts"] *= away_adj
    team.loc[team["team_alias"] == away, "ast"] *= away_adj
    team.loc[team["team_alias"] == away, "tov"] *= away_adj
    team.loc[team["team_alias"] == away, "orb"] *= away_adj
    team.loc[team["team_alias"] == away, "drb"] *= away_adj
    team.loc[team["team_alias"] == away, "stl"] *= away_adj
    team.loc[team["team_alias"] == away, "blk"] *= away_adj
    team.loc[team["team_alias"] == away, "opponent"] = home

    team = team[
        [
            "player_id",
            "player_name",
            "team_alias",
            "opponent",
            "injury",
            "p_mp_48",
            "pts",
            "ast",
            "tov",
            "orb",
            "drb",
            "stl",
            "blk",
        ]
    ]
    team["EV"] = (
        team["pts"]
        + team["orb"]
        + team["drb"]
        + 2 * team["ast"]
        + 3 * team["blk"]
        + 3 * team["stl"]
    )
    # print(home, round(team.loc[team["team_alias"] == home, "pts"].sum(), 2))
    # print(away, round(team.loc[team["team_alias"] == away, "pts"].sum(), 2))
    return team, [
        home,
        round(team.loc[team["team_alias"] == home, "pts"].sum(), 2),
        round(team.loc[team["team_alias"] == away, "pts"].sum(), 2),
        away,
    ]


# %% player names
player_names, team_id = get_player_info()
player_names = player_names.loc[player_names["code"] > 1]
player_names = player_names.sort_values(["now_cost", "team"], ascending=[False, True])

# %% fixtures by team
# team_list = player_names.groupby('team').first()
# team_list = team_list.reset_index()
fixtures = get_fixture_info(player_names.groupby("team").first().reset_index())
fixtures = fixtures.drop("id", axis=1)
fixtures["event_name"] = fixtures["event_name"].str.replace("Gameweek ", "GD_")
fixtures["event_name"] = fixtures["event_name"].str.replace(" - Day ", "_")
fixtures[["event_name", "gameweek", "gameday"]] = fixtures["event_name"].str.split(
    "_", expand=True
)

# %% get the fixtures for the given gameweek(s)
gameweeks_str = [str(gw) for gw in gws_to_run]

gw_fixtures = fixtures[
    (fixtures["gameweek"].isin(gameweeks_str)) & (fixtures["is_home"])
]

if gw_fixtures.empty:
    print(f"No fixtures found for the specified gameweeks: {gws_to_run}.")
else:
    print(f"Found {len(gw_fixtures)} fixtures for Gameweeks: {gws_to_run}")
    gw_fixtures = gw_fixtures[["team_h", "team_a", "gameweek", "gameday"]]
    gw_fixtures = gw_fixtures.merge(
        team_id, left_on=["team_h"], right_on=["id"], how="left"
    )
    gw_fixtures = gw_fixtures.merge(
        team_id, left_on=["team_a"], right_on=["id"], how="left"
    )

# %% extract data from dunks and threes
player_data = extract_epm_data()
player_data = modify_strings(player_data)
player_data = convert_string_list_to_dict(player_data)

injury_report = injury_status()
injury_report[["Status", "Type"]] = injury_report["Status"].str.split("(", expand=True)
injury_report["Type"] = injury_report["Type"].str.replace(")", "")
injury_report = injury_report[injury_report["Type"] != "Rest"]
injury_report["injury"] = 0.0
injury_report.loc[injury_report["Status"] == "Day-To-Day ", "injury"] = 0.75

player_data = pd.DataFrame(player_data)
player_data = player_data[
    [
        "season",
        "game_dt",
        "player_id",
        "player_name",
        "team_id",
        "team_alias",
        "age",
        "inches",
        "weight",
        "rookie_year",
        "position",
        "off",
        "def",
        "tot",
        "p_pct_start",
        "p_t_poss_48",
        "p_mp_48",
        "p_usg",
        "p_pts_100",
        "p_tspct",
        "p_efg",
        "p_fga_rim_100",
        "p_fga_mid_100",
        "p_fg2a_100",
        "p_fg3a_100",
        "p_fta_100",
        "p_fgpct_rim",
        "p_fgpct_mid",
        "p_fg2pct",
        "p_fg3pct",
        "p_ftpct",
        "p_ast_100",
        "p_tov_100",
        "p_orb_100",
        "p_drb_100",
        "p_stl_100",
        "p_blk_100",
    ]
]

player_data["player_name"] = player_data["player_name"].str.replace(
    "curiÅ¡ic", "Durisic"
)
player_data["player_name"] = player_data["player_name"].str.replace("Ä", "c")
player_data["player_name"] = player_data["player_name"].str.replace("", "")
player_data["player_name"] = player_data["player_name"].str.replace("Ä", "c")
player_data["player_name"] = player_data["player_name"].str.replace("Ã±", "n")
player_data["player_name"] = player_data["player_name"].str.replace("Ã¡", "a")
player_data["player_name"] = player_data["player_name"].str.replace("Ã¤", "a")
player_data["player_name"] = player_data["player_name"].str.replace("Ã´", "o")
player_data["player_name"] = player_data["player_name"].str.replace("Ã«", "e")

# %% adjust player minutes to 240 per team
player_data = player_data.merge(
    injury_report[["Player", "injury"]],
    left_on="player_name",
    right_on="Player",
    how="left",
)
player_data["injury"] = player_data["injury"].fillna(1)
player_data["p_mp_48"] *= player_data["injury"]
player_data = mins_adjustment(player_data)

player_data["adj_off"] = player_data["off"] * player_data["p_mp_48"] / 48
player_data["adj_def"] = player_data["def"] * player_data["p_mp_48"] / 48
player_data["adj_pace"] = player_data["p_t_poss_48"] * player_data["p_mp_48"] / 240

team_strength = player_data.pivot_table(
    values=["adj_off", "adj_def", "adj_pace"], index=["team_alias"], aggfunc="sum"
)
team_strength["rating"] = team_strength["adj_off"] + team_strength["adj_def"]
team_strength = team_strength.reset_index()

# %% game level projections
# game_stats = matchup_stats('OKC', 'SAC', team_strength, df_adj.copy())
gw_summary = []
results_summary = [["Home", "home pts", "away pts", "Away"]]
for f in gw_fixtures.values:
    game_stats, result = matchup_stats(f[6], f[9], team_strength, player_data.copy())
    game_stats["week"] = f[2]
    game_stats["day"] = f[3]
    game_stats["week_num"] = pd.to_numeric(f[2])
    game_stats["day_num"] = pd.to_numeric(f[3])
    gw_summary.append(game_stats)
    gw_summary.append(game_stats)
    results_summary.append(result)
    del f, game_stats, result

results_summary = pd.DataFrame(results_summary[1:], columns=results_summary[0])
results_summary["spread"] = results_summary["home pts"] - results_summary["away pts"]
results_summary["total"] = results_summary["home pts"] + results_summary["away pts"]

gw_summary = pd.concat(gw_summary)

gw_summary["gw_day_label"] = (
    "Gameweek "
    + gw_summary["week"].astype(str)
    + " - Day "
    + gw_summary["day"].astype(str)
)
label_sort_df = gw_summary[["gw_day_label", "week_num", "day_num"]].drop_duplicates()
label_sort_df = label_sort_df.sort_values(by=["week_num", "day_num"])
sorted_labels = label_sort_df["gw_day_label"].tolist()

gw_pivot = pd.pivot_table(
    gw_summary,
    index=["player_id", "player_name"],
    columns=["gw_day_label"],
    values=["EV"],
)
gw_pivot.columns = gw_pivot.columns.droplevel(0)

if gw_pivot.columns.nlevels == 1:
    ev_cols = [label for label in sorted_labels if label in gw_pivot.columns]
    other_cols = [col for col in gw_pivot.columns if col not in ev_cols]
    gw_pivot = gw_pivot[other_cols + ev_cols]

gw_pivot["EV total"] = gw_pivot.sum(axis=1, skipna=True)
gw_pivot = gw_pivot.reset_index()
gw_pivot = gw_pivot.merge(
    player_names[["code", "id", "now_cost", "team", "element_type"]],
    left_on=["player_id"],
    right_on=["code"],
    how="left",
)
gw_pivot = gw_pivot.drop("code", axis=1)
gw_pivot["efficiency"] = gw_pivot["EV total"] / gw_pivot["now_cost"]


gw_pivot["id"] = pd.to_numeric(gw_pivot["id"], errors="coerce")
gw_pivot = gw_pivot.sort_values(by="id", ascending=True, na_position="last")

all_cols = gw_pivot.columns.tolist()
final_cols_start = ["id", "player_name", "team", "now_cost", "element_type"]
other_cols = [col for col in all_cols if col not in final_cols_start]
final_cols = final_cols_start + other_cols
gw_pivot = gw_pivot[final_cols]
gw_pivot = gw_pivot.fillna(0)
gw_pivot = gw_pivot.drop("player_id", axis=1)
gw_pivot = gw_pivot.rename(columns={"player_name": "name"})
gw_pivot.to_csv(f"{output_dir}/mou.csv", index=False)
