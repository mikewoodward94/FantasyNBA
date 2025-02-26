import pandas as pd
import pulp
import re
import xlsxwriter
import uuid
import datetime


def nba_solver(
    data,
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
):
    print("Setting up and starting solve")
    team_value = data[data["id"].isin(in_team)]["now_cost"].sum()
    money = team_value + in_bank
    print(f"Money: {money}")

    # remove banned players
    data = data[~data["id"].isin(banned)]

    data = data.set_index("id")

    player_ids = data.index
    point_columns = data.columns[11:]

    # create dictionary of gameweeks + game days
    week_day_list = []
    week_day_dict = {}
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

    current_week = min(list(week_day_dict.keys()))
    current_day = min(list(week_day_dict[current_week]))

    in_team_flag = {id: 1 if id in in_team else 0 for id in player_ids}

    # create columns for team and position
    positions = pd.get_dummies(data, columns=["element_type"], prefix="pos")[
        ["pos_1", "pos_2"]
    ].astype(int)
    teams = pd.get_dummies(data, columns=["team"], prefix="team")
    teams = teams.loc[:, teams.columns.str.startswith("team_")].astype(int)

    # create dictionaries
    points = {i: {j: {} for j in week_day_dict[i]} for i in week_day_dict.keys()}
    squad_var = {i: {j: {} for j in week_day_dict[i]} for i in week_day_dict.keys()}
    team_var = {i: {j: {} for j in week_day_dict[i]} for i in week_day_dict.keys()}
    cap_var = {i: {j: {} for j in week_day_dict[i]} for i in week_day_dict.keys()}
    transfer_var = {i: {j: {} for j in week_day_dict[i]} for i in week_day_dict.keys()}

    # apply decay to transfer penalties
    decay_factor = decay
    cumulative_index = 0

    decay_dict = {}
    for week, days in sorted(week_day_dict.items()):
        decay_dict[week] = {}
        for day in days:
            decay_dict[week][day] = decay_factor**cumulative_index
            cumulative_index += 1

    base_penalty = transfer_penalty

    penalty_dict = {
        week: {day: base_penalty[day] for day in days if day in base_penalty}
        for week, days in week_day_dict.items()
    }

    # Create variables for each gameweek + gameday IN ORDER accounting for varying week lengths
    for a in week_day_dict.keys():
        for b in week_day_dict[a]:

            position = None
            current_position = 0

            for key, values in week_day_dict.items():
                if key < a:
                    current_position += len(values)
                elif key == a:
                    for value in values:
                        current_position += 1
                        if value == b:
                            position = current_position
                            break
                if position is not None:
                    break

            for i in player_ids:
                points[a][b][i] = data[point_columns[position - 1]][i]
                squad_var[a][b][i] = pulp.LpVariable(
                    "gwk" + str(a) + "gdy" + str(b) + "x" + str(i), cat="Binary"
                )
                team_var[a][b][i] = pulp.LpVariable(
                    "gwk" + str(a) + "gdy" + str(b) + "y" + str(i), cat="Binary"
                )
                cap_var[a][b][i] = pulp.LpVariable(
                    "gwk" + str(a) + "gdy" + str(b) + "c" + str(i), cat="Binary"
                )
                transfer_var[a][b][i] = pulp.LpVariable(
                    f"transfer_gwk{a}_gdy{b}_x{i}", cat="Binary"
                )

    # Start Problem
    prob = pulp.LpProblem("Optimiser", pulp.LpMaximize)

    # Objective Function
    if day_solve == True:
        prob += pulp.lpSum(
            [
                ((points[a][b][i] * team_var[a][b][i]))
                for a in week_day_dict.keys()
                for b in week_day_dict[a]
                for i in player_ids
            ]
        )
    else:
        prob += pulp.lpSum(
            [
                (
                    (points[a][b][i] * team_var[a][b][i])
                    + (points[a][b][i] * cap_var[a][b][i])
                    - (transfer_var[a][b][i] * penalty_dict[a][b] * decay_dict[a][b])
                )
                for a in week_day_dict.keys()
                for b in week_day_dict[a]
                for i in player_ids
            ]
        )

    for a in week_day_dict.keys():

        if cap_used == True and a == current_week:
            prob += (
                pulp.lpSum(
                    [cap_var[a][b][i] for b in week_day_dict[a] for i in player_ids]
                )
                == 0
            )
        else:
            prob += (
                pulp.lpSum(
                    [cap_var[a][b][i] for b in week_day_dict[a] for i in player_ids]
                )
                == 1
            )

        for b in week_day_dict[a]:
            prob += pulp.lpSum([squad_var[a][b][i] for i in player_ids]) == 10
            prob += pulp.lpSum([team_var[a][b][i] for i in player_ids]) == 5

            prob += (
                pulp.lpSum(
                    [positions["pos_1"][i] * team_var[a][b][i] for i in player_ids]
                )
                >= 2
            )
            prob += (
                pulp.lpSum(
                    [positions["pos_1"][i] * team_var[a][b][i] for i in player_ids]
                )
                <= 3
            )
            prob += (
                pulp.lpSum(
                    [positions["pos_1"][i] * squad_var[a][b][i] for i in player_ids]
                )
                == 5
            )

            if day_solve == False:
                prob += (
                    pulp.lpSum(
                        [data["now_cost"][i] * squad_var[a][b][i] for i in player_ids]
                    )
                    <= money
                )

            for team in teams:
                prob += (
                    pulp.lpSum(
                        [teams[team][i] * squad_var[a][b][i] for i in player_ids]
                    )
                    <= 2
                )

            for i in player_ids:
                prob += team_var[a][b][i] <= squad_var[a][b][i]
                prob += cap_var[a][b][i] <= team_var[a][b][i]

    if day_solve == False:
        # Track transfers across days and weeks
        for a in week_day_dict.keys():
            for b in week_day_dict[a]:
                for i in player_ids:
                    # Transfer event: 1 if the player was added or removed on this day, 0 otherwise

                    # Transfer check within the same week (compare with the previous day in the same week)
                    if a == current_week and b == current_day and wildcard == True:
                        prob += transfer_var[a][b][i] == 0
                    elif a == current_week and b == current_day and wildcard == False:
                        prob += (
                            transfer_var[a][b][i]
                            >= squad_var[a][b][i] - in_team_flag[i]
                        )
                    elif b > 1:
                        current_index = week_day_dict[a].index(b)
                        previous_day = week_day_dict[a][current_index - 1]
                        prob += (
                            transfer_var[a][b][i]
                            >= squad_var[a][b][i] - squad_var[a][previous_day][i]
                        )
                    else:
                        # For the first day of the new week, compare with the last day of the previous week
                        if a > current_week:
                            last_day_of_prev_week = max(week_day_dict[a - 1])
                            prob += (
                                transfer_var[a][b][i]
                                >= squad_var[a][b][i]
                                - squad_var[a - 1][last_day_of_prev_week][i]
                            )
                        else:
                            # For the very first week, no transfers should have occurred before
                            prob += transfer_var[a][b][i] == 0

            if a > current_week:
                prob += (
                    pulp.lpSum(
                        [
                            transfer_var[a][b][i]
                            for b in week_day_dict[a]
                            for i in player_ids
                        ]
                    )
                    <= 2
                )
            else:
                prob += (
                    pulp.lpSum(
                        [
                            transfer_var[a][b][i]
                            for b in week_day_dict[a]
                            for i in player_ids
                        ]
                    )
                    <= transfers_left
                )

    for i in locked:
        prob += squad_var[current_week][current_day][i] == 1

    if wildcard == False and day_solve == False:
        prob += (
            pulp.lpSum([squad_var[current_week][current_day][i] for i in in_team]) >= 8
        )

    prob += (
        pulp.lpSum([squad_var[current_week][current_day][i] for i in gd_banned]) == 0
    )

    prob.solve(pulp.HiGHS(timeLimit=max_time, gapRel=gap))
    print("Score: ", pulp.value(prob.objective))
    print("Status: ", pulp.LpStatus[prob.status])

    output = data[["name", "now_cost", "element_type"]].reset_index()

    combined_df = output.copy()
    combined_df["current"] = combined_df["id"].map(in_team_flag)

    ev_mapping = {}
    for a in week_day_dict.keys():
        for b in week_day_dict[a]:
            gw_day_key = f"Gameweek {a} - Day {b}"
            if gw_day_key in data.columns:
                ev_mapping[(a, b)] = gw_day_key

    for a in week_day_dict.keys():
        for b in week_day_dict[a]:
            day_str = f"{a}_{b}"
            # Add squad columns (1 if in squad, 0 otherwise)
            combined_df[f"squad_{day_str}"] = combined_df["id"].apply(
                lambda x: 1 if round(squad_var[a][b][x].varValue) == 1 else 0
            )
            # Add team columns (1 if in team, 0 if benched)
            combined_df[f"team_{day_str}"] = combined_df["id"].apply(
                lambda x: 1 if round(team_var[a][b][x].varValue) == 1 else 0
            )
            # Add captain columns (1 if captain, 0 otherwise)
            combined_df[f"cap_{day_str}"] = combined_df["id"].apply(
                lambda x: 1 if round(cap_var[a][b][x].varValue) == 1 else 0
            )

            ev_key = (a, b)
            if ev_key in ev_mapping:
                ev_col = ev_mapping[ev_key]
                combined_df[f"xPts_{day_str}"] = data[ev_col].reset_index()[
                    f"Gameweek {a} - Day {b}"
                ]

    squad_columns = [col for col in combined_df.columns if col.startswith("squad_")]
    combined_df = combined_df[combined_df[squad_columns].eq(1).any(axis=1)]

    time_now = datetime.datetime.now()
    stamp = time_now.strftime("%Y-%m-%d_%H-%M-%S")

    writer = pd.ExcelWriter(f"../output/NBA_Squad_{stamp}.xlsx", engine="xlsxwriter")
    combined_df.to_excel(writer, sheet_name="Team_Plan", index=False)
    writer.close()
    print(f"Squad and Transfer Plan output to NBA_Squad_{stamp}.xlsx")

    sell_summary = []
    buy_summary = []
    team_summary = dict()
    bench_summary = dict()

    for day in week_day_list:
        a, b = day[0], day[1]
        day_str = f"{a}_{b}"
        gw_day_str = f"Gameweek {a} - Day {b}"

        day_team_df = combined_df[combined_df[f"team_{day_str}"] == 1].copy()
        day_bench_df = combined_df[
            (combined_df[f"squad_{day_str}"] == 1)
            & (combined_df[f"team_{day_str}"] == 0)
        ].copy()

        if gw_day_str in data.columns:
            day_team_df["display_name"] = day_team_df.apply(
                lambda row: (
                    f"{row['name']}({data.loc[row['id'], gw_day_str]:.2f})"
                    if not pd.isna(data.loc[row["id"], gw_day_str])
                    else row["name"]
                ),
                axis=1,
            )

            day_bench_df["display_name"] = day_bench_df.apply(
                lambda row: (
                    f"{row['name']}({data.loc[row['id'], gw_day_str]:.2f})"
                    if not pd.isna(data.loc[row["id"], gw_day_str])
                    else row["name"]
                ),
                axis=1,
            )
        else:
            day_team_df["display_name"] = day_team_df["name"]
            day_bench_df["display_name"] = day_bench_df["name"]

        captain_ids = combined_df[combined_df[f"cap_{day_str}"] == 1]["id"].tolist()
        if captain_ids:
            day_team_df["display_name"] = day_team_df.apply(
                lambda row: (
                    f"{row['display_name']} (C)"
                    if row["id"] in captain_ids
                    else row["display_name"]
                ),
                axis=1,
            )

        team_summary[day_str] = day_team_df["display_name"].tolist()
        bench_summary[day_str] = day_bench_df["display_name"].tolist()

    # current gws
    first_gw_day = f"{current_week}_{current_day}"
    first_squad_col = f"squad_{first_gw_day}"

    print()
    print(f"{first_gw_day}: ")
    for _, row in combined_df.iterrows():
        if row["current"] != row[first_squad_col]:
            if row["current"] == 1:
                print(f"Sell: {row['name']}, Price: {row['now_cost']}")
                sell_summary.append(row["name"])
            else:
                print(f"Buy: {row['name']}, Price: {row['now_cost']}")
                buy_summary.append(row["name"])

    print("Line-up: ")
    front_court = []
    back_court = []
    for _, row in combined_df.iterrows():
        if row[f"team_{first_gw_day}"] == 1:
            ev_col = f"Gameweek {current_week} - Day {current_day}"
            player_name = f"{row['name']}({data.loc[row['id'], ev_col]:.2f})"
            if row[f"cap_{first_gw_day}"] == 1:
                player_name += " (C)"
            if row["element_type"] == 2:
                front_court.append(player_name)
            else:
                back_court.append(player_name)

    print("\t" + ", ".join(front_court))
    print("\t" + ", ".join(back_court) + "\n")

    print("Benched: \n" + "\t" + ", ".join(bench_summary[first_gw_day]) + "\n")

    day_xPts = 0
    for _, row in combined_df.iterrows():
        if row[f"team_{first_gw_day}"] == 1:
            ev_col = f"Gameweek {current_week} - Day {current_day}"
            if row[f"cap_{first_gw_day}"] == 1:
                day_xPts += 2 * data.loc[row["id"], ev_col]
            else:
                day_xPts += data.loc[row["id"], ev_col]

    print(f"Cumulative xPts: {day_xPts:.2f}")
    print()

    # future gws
    squad_day_cols = [col for col in combined_df.columns if col.startswith("squad_")]
    squad_day_cols.sort()

    for i in range(1, len(squad_day_cols)):
        current_day = squad_day_cols[i].replace("squad_", "")
        prev_day = squad_day_cols[i - 1].replace("squad_", "")

        print(f"{current_day} : ")
        for _, row in combined_df.iterrows():
            if row[squad_day_cols[i - 1]] != row[squad_day_cols[i]]:
                if row[squad_day_cols[i - 1]] == 1:
                    print(f"Sell: {row['name']}, Price: {row['now_cost']}")
                else:
                    print(f"Buy: {row['name']}, Price: {row['now_cost']}")
        print("Line-up: ")
        front_court = []
        back_court = []
        for _, row in combined_df.iterrows():
            if row[f"team_{current_day}"] == 1:
                ev_col = f"Gameweek {current_day.split('_')[0]} - Day {current_day.split('_')[1]}"
                player_name = f"{row['name']}({data.loc[row['id'], ev_col]:.2f})"
                if row[f"cap_{current_day}"] == 1:
                    player_name += " (C)"
                if row["element_type"] == 2:
                    front_court.append(player_name)
                else:
                    back_court.append(player_name)

        print("\t" + ", ".join(front_court))

        print("\t" + ", ".join(back_court) + "\n")

        print("Benched: \n " + "\t" + ", ".join(bench_summary[current_day]) + "\n")

        day_xPts = 0
        for _, row in combined_df.iterrows():
            if row[f"team_{current_day}"] == 1:
                ev_col = f"Gameweek {current_day.split('_')[0]} - Day {current_day.split('_')[1]}"
                if row[f"cap_{current_day}"] == 1:
                    day_xPts += 2 * data.loc[row["id"], ev_col]
                else:
                    day_xPts += data.loc[row["id"], ev_col]

        print(f"Cumulative xPts: {day_xPts:.2f}")
        print()

    print()
