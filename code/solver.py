import pandas as pd
import sasoptpy as so  # type: ignore
import highspy
import re
from pathlib import Path
import os
import time


BINARY_THRESHOLD = 0.5


def nba_solver(
    data,
    locked,
    banned,
    gd_banned,
    use_wc,
    use_as,
    booked_transfers,
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
    iteration=0,
    previous_solutions=None,
    iteration_criteria="",
    iteration_difference=1,
    num_iterations=1,
):
    team_value = data[data["id"].isin(in_team)]["now_cost"].sum()
    money = team_value + in_bank
    print(f"Money: {money}")

    pristine_player_ids = data["id"].tolist()
    pristine_in_team_flag = {
        id: 1 if id in in_team else 0 for id in pristine_player_ids
    }
    pristine_output_df = data[["id", "name", "now_cost", "element_type"]].copy()
    pristine_output_df["current"] = pristine_output_df["id"].map(pristine_in_team_flag)

    pristine_data_for_printing = data.copy()

    data = data[~data["id"].isin(banned)]
    data = data.set_index("id")

    player_ids = data.index.tolist()
    missing_players_in_solver = [pid for pid in in_team if pid not in player_ids]
    if missing_players_in_solver:
        print(
            f"CRITICAL ERROR: The following players from 'in_team' are missing from the EV data (player_ids): {missing_players_in_solver}"
        )
        print(
            "This is likely due to the 'value_cutoff' setting or an incomplete 'NBA_EV.csv' file."
        )
        print("The solver cannot continue as this will result in a 9-player team.")
        raise ValueError(f"Missing players from in_team: {missing_players_in_solver}")

    point_columns = [
        col for col in data.columns if re.match(r"^Gameweek \d+ - Day \d+$", col)
    ]
    print(f"Found {len(point_columns)} point columns: {point_columns}")

    filtered_point_columns = []
    for col in point_columns:
        week = int(re.findall(r"(\d+)", col)[0])
        day = int(re.findall(r"(\d+)", col)[1])

        in_range = True
        if week < first_gw or (week == first_gw and day < first_gd):
            in_range = False
        if week > final_gw or (week == final_gw and day > final_gd):
            in_range = False

        if in_range:
            filtered_point_columns.append(col)

    point_columns = filtered_point_columns

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

    in_team_flag_for_solver = {id: 1 if id in in_team else 0 for id in player_ids}

    # create columns for team and position
    positions = pd.get_dummies(data, columns=["element_type"], prefix="pos")[
        ["pos_1", "pos_2"]
    ].astype(int)
    teams = pd.get_dummies(data, columns=["team"], prefix="team")
    teams = teams.loc[:, teams.columns.str.startswith("team_")].astype(int)

    problem_name = "nba_optimizer"
    model = so.Model(name=problem_name)

    # flattening
    all_week_days = [(w, d) for w in week_day_dict.keys() for d in week_day_dict[w]]

    # sasoptpy variables
    squad_var = {}
    team_var = {}
    cap_var = {}
    transfer_var = {}

    for i in player_ids:
        for w, d in all_week_days:
            squad_var[i, w, d] = model.add_variable(
                name=f"squad_{i}_{w}_{d}", vartype=so.binary
            )
            team_var[i, w, d] = model.add_variable(
                name=f"team_{i}_{w}_{d}", vartype=so.binary
            )
            cap_var[i, w, d] = model.add_variable(
                name=f"cap_{i}_{w}_{d}", vartype=so.binary
            )
            transfer_var[i, w, d] = model.add_variable(
                name=f"transfer_{i}_{w}_{d}", vartype=so.binary
            )

    # points dict
    points = {}
    position_map = {}
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

            position_map[(a, b)] = position
            for i in player_ids:
                points[(i, a, b)] = data[point_columns[position - 1]][i]

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
        week: {
            day: base_penalty[str(day)]
            for day in week_day_dict[week]
            if str(day) in base_penalty
        }
        for week in week_day_dict.keys()
    }

    # Main stuff
    if day_solve:
        objective_expr = so.expr_sum(
            points[(i, a, b)] * team_var[i, a, b]
            for a in week_day_dict.keys()
            for b in week_day_dict[a]
            for i in player_ids
        )
    else:
        objective_expr = so.expr_sum(
            (
                (
                    (points[(i, a, b)] * team_var[i, a, b])
                    + (
                        points[(i, a, b)]
                        * (squad_var[i, a, b] - team_var[i, a, b])
                        * 0.99
                    )
                )
                if f"{a}_{b}" in use_as
                else (
                    (points[(i, a, b)] * team_var[i, a, b])
                    + (points[(i, a, b)] * cap_var[i, a, b])
                    - (transfer_var[i, a, b] * penalty_dict[a][b] * decay_dict[a][b])
                )
            )
            for a in week_day_dict.keys()
            for b in week_day_dict[a]
            for i in player_ids
        )

    model.set_objective(-objective_expr, sense="N", name="total_points")

    # post allstar team reset
    if not day_solve:
        for as_day_str in use_as:
            as_week, as_day = -1, -1
            try:
                as_week_str, as_day_str_int = as_day_str.strip().split("_")
                as_week = int(as_week_str)
                as_day = int(as_day_str_int)
            except ValueError:
                print(f"Warning: Invalid AllStar day format '{as_day_str}'. Skipping.")
                continue

            if as_week != -1 and as_day != -1:
                a_before, b_before = -1, -1
                a_after, b_after = -1, -1

                try:
                    if as_day > 1 and as_week in week_day_dict:
                        as_day_index = week_day_dict[as_week].index(as_day)
                        if as_day_index > 0:
                            a_before, b_before = (
                                as_week,
                                week_day_dict[as_week][as_day_index - 1],
                            )
                    elif as_week > current_week:
                        a_before = as_week - 1
                        if a_before in week_day_dict:
                            b_before = max(week_day_dict[a_before])
                    elif as_week == current_week and as_day > current_day:
                        as_day_index = week_day_dict[as_week].index(as_day)
                        if as_day_index > 0:
                            a_before, b_before = (
                                as_week,
                                week_day_dict[as_week][as_day_index - 1],
                            )

                    if as_week in week_day_dict:
                        as_day_index = week_day_dict[as_week].index(as_day)
                        if as_day_index < len(week_day_dict[as_week]) - 1:
                            a_after, b_after = (
                                as_week,
                                week_day_dict[as_week][as_day_index + 1],
                            )
                        elif as_week < final_gw:
                            a_after = as_week + 1
                            if a_after in week_day_dict:
                                b_after = min(week_day_dict[a_after])

                    if a_after != -1:
                        if a_before != -1:
                            print(
                                f"Applying AllStar 'team return' constraint: Day {a_after}_{b_after} team = Day {a_before}_{b_before} team."
                            )
                            model.add_constraints(
                                (
                                    squad_var[i, a_after, b_after]
                                    == squad_var[i, a_before, b_before]
                                    for i in player_ids
                                ),
                                name=f"as_return_{as_week}_{as_day}",
                            )
                        elif as_week == current_week and as_day == current_day:
                            model.add_constraints(
                                (
                                    squad_var[i, a_after, b_after]
                                    == in_team_flag_for_solver[i]
                                    for i in player_ids
                                ),
                                name=f"as_return_initial_{as_week}_{as_day}",
                            )

                except (ValueError, KeyError, IndexError):
                    pass

    # constraints
    for a in week_day_dict.keys():
        if cap_used and a == current_week:
            model.add_constraint(
                so.expr_sum(
                    cap_var[i, a, b] for b in week_day_dict[a] for i in player_ids
                )
                == 0,
                name=f"no_cap_week_{a}",
            )
        else:
            model.add_constraint(
                so.expr_sum(
                    cap_var[i, a, b] for b in week_day_dict[a] for i in player_ids
                )
                == 1,
                name=f"cap_week_{a}",
            )

        for b in week_day_dict[a]:
            current_day_str = f"{a}_{b}"
            is_this_day_allstar = current_day_str in use_as

            if is_this_day_allstar:
                model.add_constraint(
                    so.expr_sum(cap_var[i, a, b] for i in player_ids) == 0,
                    name=f"no_cap_as_{a}_{b}",
                )

            model.add_constraint(
                so.expr_sum(squad_var[i, a, b] for i in player_ids) == 10,
                name=f"squad_size_{a}_{b}",
            )
            model.add_constraint(
                so.expr_sum(team_var[i, a, b] for i in player_ids) == 5,
                name=f"team_size_{a}_{b}",
            )

            model.add_constraint(
                so.expr_sum(
                    positions["pos_1"][i] * team_var[i, a, b] for i in player_ids
                )
                >= 2,
                name=f"team_pos1_min_{a}_{b}",
            )
            model.add_constraint(
                so.expr_sum(
                    positions["pos_1"][i] * team_var[i, a, b] for i in player_ids
                )
                <= 3,
                name=f"team_pos1_max_{a}_{b}",
            )
            model.add_constraint(
                so.expr_sum(
                    positions["pos_1"][i] * squad_var[i, a, b] for i in player_ids
                )
                == 5,
                name=f"squad_pos1_{a}_{b}",
            )

            if not day_solve and not is_this_day_allstar:
                model.add_constraint(
                    so.expr_sum(
                        data["now_cost"][i] * squad_var[i, a, b] for i in player_ids
                    )
                    <= money,
                    name=f"budget_{a}_{b}",
                )

            for team in teams:
                model.add_constraint(
                    so.expr_sum(teams[team][i] * squad_var[i, a, b] for i in player_ids)
                    <= 2,
                    name=f"team_limit_{team}_{a}_{b}",
                )

            model.add_constraints(
                (team_var[i, a, b] <= squad_var[i, a, b] for i in player_ids),
                name=f"team_squad_rel_{a}_{b}",
            )
            model.add_constraints(
                (cap_var[i, a, b] <= team_var[i, a, b] for i in player_ids),
                name=f"cap_team_rel_{a}_{b}",
            )

    # transfers
    if not day_solve:
        for a in week_day_dict.keys():
            for b in week_day_dict[a]:
                current_day_str = f"{a}_{b}"
                is_this_day_wildcard = current_day_str in use_wc
                is_this_day_allstar = current_day_str in use_as

                a_prev, b_prev = -1, -1
                is_prev_day_allstar = False
                is_first_day = a == current_week and b == current_day

                if not is_first_day:
                    if b > 1:
                        current_index = week_day_dict[a].index(b)
                        a_prev, b_prev = a, week_day_dict[a][current_index - 1]
                    elif a > current_week:
                        a_prev = a - 1
                        if a_prev in week_day_dict:
                            b_prev = max(week_day_dict[a_prev])
                        else:
                            a_prev = -1

                    if a_prev != -1:
                        prev_day_str = f"{a_prev}_{b_prev}"
                        if prev_day_str in use_as:
                            is_prev_day_allstar = True

                for i in player_ids:
                    if is_this_day_wildcard or is_this_day_allstar:
                        model.add_constraint(
                            transfer_var[i, a, b] == 0,
                            name=f"no_transfer_chip_{i}_{a}_{b}",
                        )
                    elif is_prev_day_allstar:
                        model.add_constraint(
                            transfer_var[i, a, b] == 0,
                            name=f"no_transfer_after_as_{i}_{a}_{b}",
                        )
                    else:
                        if is_first_day:
                            model.add_constraint(
                                transfer_var[i, a, b]
                                >= squad_var[i, a, b] - in_team_flag_for_solver[i],
                                name=f"transfer_first_{i}_{a}_{b}",
                            )
                        elif a_prev != -1:
                            model.add_constraint(
                                transfer_var[i, a, b]
                                >= squad_var[i, a, b] - squad_var[i, a_prev, b_prev],
                                name=f"transfer_{i}_{a}_{b}",
                            )
                        else:
                            model.add_constraint(
                                transfer_var[i, a, b]
                                >= squad_var[i, a, b] - in_team_flag_for_solver[i],
                                name=f"transfer_default_{i}_{a}_{b}",
                            )

            if a > current_week:
                model.add_constraint(
                    so.expr_sum(
                        transfer_var[i, a, b]
                        for b in week_day_dict[a]
                        for i in player_ids
                    )
                    <= 2,
                    name=f"transfer_limit_{a}",
                )
            else:
                model.add_constraint(
                    so.expr_sum(
                        transfer_var[i, a, b]
                        for b in week_day_dict[a]
                        for i in player_ids
                    )
                    <= transfers_left,
                    name=f"transfer_limit_current_{a}",
                )

    model.add_constraints(
        (
            squad_var[i, current_week, current_day] == 1
            for i in locked
            if i in player_ids
        ),
        name="locked_players",
    )

    first_day_str = f"{current_week}_{current_day}"
    is_wildcard_active_today = first_day_str in use_wc
    is_allstar_active_today = first_day_str in use_as

    if not is_wildcard_active_today and not is_allstar_active_today and not day_solve:
        model.add_constraint(
            so.expr_sum(
                squad_var[i, current_week, current_day]
                for i in in_team
                if i in player_ids
            )
            >= 8,
            name="min_players_from_current",
        )

    model.add_constraint(
        so.expr_sum(
            squad_var[i, current_week, current_day]
            for i in gd_banned
            if i in player_ids
        )
        == 0,
        name="banned_today",
    )

    if not day_solve and booked_transfers:
        print("Adding booked transfer constraints")
        for bt in booked_transfers:
            bt_week = bt.get("gw", None)
            bt_day = bt.get("day", None)

            if bt_week is None or bt_day is None:
                continue

            if bt_week not in week_day_dict or bt_day not in week_day_dict[bt_week]:
                print(
                    f"Warning: Booked transfer for GW{bt_week} Day{bt_day} is outside solve range"
                )
                continue

            player_in = bt.get("transfer_in", None)
            player_out = bt.get("transfer_out", None)

            if player_in is not None and player_in in player_ids:
                model.add_constraint(
                    squad_var[player_in, bt_week, bt_day] == 1,
                    name=f"booked_in_{bt_week}_{bt_day}_{player_in}",
                )

            if player_out is not None and player_out in player_ids:
                model.add_constraint(
                    squad_var[player_out, bt_week, bt_day] == 0,
                    name=f"booked_out_{bt_week}_{bt_day}_{player_out}",
                )

    # iters
    solutions = []

    for iteration_num in range(num_iterations):
        print(f"\n=== Solving Iteration {iteration_num} ===")

        tmp_folder = Path() / "tmp"
        tmp_folder.mkdir(exist_ok=True, parents=True)

        mps_file_name = f"tmp/{problem_name}_{iteration_num}.mps"
        model.export_mps(mps_file_name)
        print(f"Exported problem: {problem_name}_{iteration_num}")

        solver_instance = highspy.Highs()
        solver_instance.readModel(str(mps_file_name))
        solver_instance.setOptionValue("parallel", "on")
        solver_instance.setOptionValue("time_limit", max_time)
        solver_instance.setOptionValue("mip_rel_gap", gap)
        solver_instance.setOptionValue("log_to_console", True)

        solver_instance.run()
        solution = solver_instance.getSolution()

        model_status = solver_instance.getModelStatus()
        if model_status != highspy.HighsModelStatus.kOptimal:
            if iteration_num > 0:
                break
            else:
                return solutions

        values = list(solution.col_value)

        for idx, v in enumerate(model.get_variables()):
            v.set_value(values[idx])

        print("Score: ", -model.get_objective_value())
        print("Status: ", model_status)

        # results as df for printing (prisitint sounds so funky ik lmaoo)
        combined_df = pristine_output_df.copy()

        ev_mapping = {}
        for a in week_day_dict.keys():
            for b in week_day_dict[a]:
                gw_day_key = f"Gameweek {a} - Day {b}"
                if gw_day_key in data.columns:
                    ev_mapping[(a, b)] = gw_day_key

        for a in week_day_dict.keys():
            for b in week_day_dict[a]:
                day_str = f"{a}_{b}"

                combined_df[f"squad_{day_str}"] = combined_df["id"].apply(
                    lambda x: 1
                    if x in player_ids
                    and squad_var[x, a, b].get_value() > BINARY_THRESHOLD
                    else 0
                )
                combined_df[f"team_{day_str}"] = combined_df["id"].apply(
                    lambda x: 1
                    if x in player_ids
                    and team_var[x, a, b].get_value() > BINARY_THRESHOLD
                    else 0
                )
                combined_df[f"cap_{day_str}"] = combined_df["id"].apply(
                    lambda x: 1
                    if x in player_ids
                    and cap_var[x, a, b].get_value() > BINARY_THRESHOLD
                    else 0
                )

                ev_key = (a, b)
                if ev_key in ev_mapping:
                    ev_col = ev_mapping[ev_key]
                    points_map = pristine_data_for_printing.set_index("id")[ev_col]
                    combined_df[f"xPts_{day_str}"] = combined_df["id"].map(points_map)

        full_player_df = combined_df.copy()
        squad_columns = [col for col in combined_df.columns if col.startswith("squad_")]
        combined_df = combined_df[combined_df[squad_columns].eq(1).any(axis=1)]

        sell_summary_names = []
        buy_summary_names = []
        sell_summary_ids = []
        buy_summary_ids = []

        first_gw_day = f"{current_week}_{current_day}"
        first_squad_col = f"squad_{first_gw_day}"

        for _, row in full_player_df.iterrows():
            if row["current"] != row[first_squad_col]:
                if row["current"] == 1:
                    sell_summary_names.append(row["name"])
                    sell_summary_ids.append(row["id"])
                else:
                    buy_summary_names.append(row["name"])
                    buy_summary_ids.append(row["id"])

        first_day_lineup_ids = []
        team_col = f"team_{first_gw_day}"
        for _, row in combined_df.iterrows():
            if row[team_col] == 1:
                first_day_lineup_ids.append(row["id"])

        all_chips = []
        for wc_day in use_wc:
            if wc_day:
                try:
                    wc_week, wc_day_str = wc_day.split("_")
                    if (
                        int(wc_week) in week_day_dict
                        and int(wc_day_str) in week_day_dict[int(wc_week)]
                    ):
                        all_chips.append(f"WC{wc_day}")
                except:  # noqa: E722
                    pass

        for as_day in use_as:
            if as_day:
                try:
                    as_week, as_day_str = as_day.split("_")
                    if (
                        int(as_week) in week_day_dict
                        and int(as_day_str) in week_day_dict[int(as_week)]
                    ):
                        all_chips.append(f"AS{as_day}")
                except:  # noqa: E722
                    pass

        chip_horizon_str = ", ".join(all_chips) if all_chips else "-"
        first_day_sells_str = (
            ", ".join(sell_summary_names) if sell_summary_names else "-"
        )
        first_day_buys_str = ", ".join(buy_summary_names) if buy_summary_names else "-"

        result = {
            "iter": iteration_num,
            "score": -model.get_objective_value(),
            "status": "Optimal",
            "sell": first_day_sells_str,
            "buy": first_day_buys_str,
            "chip": chip_horizon_str,
            "sell_ids": sell_summary_ids,
            "buy_ids": buy_summary_ids,
            "full_player_df": full_player_df,
            "week_day_list": week_day_list,
            "current_week": current_week,
            "current_day": current_day,
            "first_day_lineup_ids": first_day_lineup_ids,
            "use_wc": use_wc,
            "use_as": use_as,
            "picks_df": combined_df,
        }

        solutions.append(result)

        try:
            time.sleep(0.1)
            os.unlink(mps_file_name)
        except:  # noqa: E722
            pass

        if num_iterations == 1:
            return solutions

        if iteration_criteria == "this_day_transfer_in":
            transferred_in_players = [
                p
                for p in player_ids
                if transfer_var[p, current_week, current_day].get_value()
                > BINARY_THRESHOLD
            ]
            not_transferred_in_players = [
                p
                for p in player_ids
                if transfer_var[p, current_week, current_day].get_value()
                < BINARY_THRESHOLD
            ]

            actions = so.expr_sum(
                1 - transfer_var[p, current_week, current_day]
                for p in transferred_in_players
            ) + so.expr_sum(
                transfer_var[p, current_week, current_day]
                for p in not_transferred_in_players
            )

            model.add_constraint(
                actions >= iteration_difference,
                name=f"iter_{iteration_num}_diff_transfer_in",
            )

        elif iteration_criteria == "this_day_transfer_out":
            eligible_out_players = [
                p for p in player_ids if in_team_flag_for_solver[p] == 1
            ]

            transferred_out_set = {
                p
                for p in eligible_out_players
                if squad_var[p, current_week, current_day].get_value()
                < BINARY_THRESHOLD
            }
            not_transferred_out_set = {
                p for p in eligible_out_players if p not in transferred_out_set
            }

            actions_was_out = so.expr_sum(
                squad_var[p, current_week, current_day] for p in transferred_out_set
            )

            actions_was_in = so.expr_sum(
                1 - squad_var[p, current_week, current_day]
                for p in not_transferred_out_set
            )

            model.add_constraint(
                actions_was_out + actions_was_in >= iteration_difference,
                name=f"iter_{iteration_num}_diff_transfer_out",
            )

        elif iteration_criteria == "this_day_transfer_in_out":
            transferred_in_players = [
                p
                for p in player_ids
                if transfer_var[p, current_week, current_day].get_value()
                > BINARY_THRESHOLD
            ]
            not_transferred_in_players = [
                p
                for p in player_ids
                if transfer_var[p, current_week, current_day].get_value()
                < BINARY_THRESHOLD
            ]
            actions_in = so.expr_sum(
                1 - transfer_var[p, current_week, current_day]
                for p in transferred_in_players
            ) + so.expr_sum(
                transfer_var[p, current_week, current_day]
                for p in not_transferred_in_players
            )

            eligible_out_players = [
                p for p in player_ids if in_team_flag_for_solver[p] == 1
            ]
            transferred_out_set = {
                p
                for p in eligible_out_players
                if squad_var[p, current_week, current_day].get_value()
                < BINARY_THRESHOLD
            }
            not_transferred_out_set = {
                p for p in eligible_out_players if p not in transferred_out_set
            }
            actions_out = so.expr_sum(
                squad_var[p, current_week, current_day] for p in transferred_out_set
            ) + so.expr_sum(
                1 - squad_var[p, current_week, current_day]
                for p in not_transferred_out_set
            )

            model.add_constraint(
                actions_in + actions_out >= iteration_difference,
                name=f"iter_{iteration_num}_diff_transfer_in_out",
            )

        elif iteration_criteria == "this_day_lineup":
            # the only which uses iteration_difference i think
            if first_day_lineup_ids:
                model.add_constraint(
                    so.expr_sum(
                        team_var[p, current_week, current_day]
                        for p in first_day_lineup_ids
                    )
                    <= len(first_day_lineup_ids) - iteration_difference,
                    name=f"iter_{iteration_num}_diff_lineup",
                )

        # end of iteration

    return solutions
