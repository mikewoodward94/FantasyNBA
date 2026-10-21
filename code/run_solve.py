import requests
import pandas as pd
import numpy as np
import json
import re
import subprocess
import sys
import datetime
from tabulate import tabulate  # type: ignore

from solver import nba_solver
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Windows consoles still default to cp1252, which cannot encode the "∞" the
# squad printout uses for a day where transfers are free.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def load_settings():
    with open(DATA_DIR / "settings.json") as f:
        options = json.load(f)
    return options


settings = load_settings()
(
    info_source,
    value_cutoff,
    decay,
    horizon,
    horizon_start,
    horizon_end,
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
    refresh_ev,
    no_team,
) = (
    settings["info_source"],
    settings["value_cutoff"],
    settings["decay"],
    settings["horizon"],
    settings.get("start"),
    settings.get("end"),
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
    settings.get("refresh_ev", True),
    settings.get("no_team", False),
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
        if result.get("no_team", False) and i == 1:
            chip_text = "New Squad"
        elif day_str in wildcard:
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
        # the opening build of a fresh squad costs no transfers, same as a chip
        is_free_build = result.get("no_team", False) and i == 1

        chip_played_str = ""
        if is_free_build:
            chip_played_str = " (New Squad)"
        elif is_wc_day:
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

        if not (is_as_day or is_wc_day or is_free_build):
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
    horizon,
    horizon_start,
    horizon_end,
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
    ev_sheet,
):
    static = get_static()
    first_gw, first_gd, final_gw, final_gd = resolve_horizon(
        static, horizon, horizon_start, horizon_end
    )

    player_info = None
    if info_source == "API":
        print("Retrieving player data from Fantasy NBA API")
        player_info = get_player_info()
        player_info.to_csv(DATA_DIR / "player_info.csv", index=False)

    in_team, in_team_sell_price, cap_used, transfers_left, in_bank, current_api_gw = (
        read_team_json(first_gw)
    )

    effective_transfers_left = transfers_left
    if first_gw > current_api_gw:
        effective_transfers_left = 2

    print("Chips:")
    validate_chips(static, get_chips_played(), use_wc, use_as, chip_limits)

    if should_refresh_ev(ev_sheet, static, first_gw, first_gd, final_gw, final_gd):
        run_mou_ev()

    player_data = read_ev_sheet(ev_sheet)
    check_ev_coverage(player_data, static, first_gw, first_gd, final_gw, final_gd)
    player_data = refresh_prices(player_data, player_info)

    pt_cols = [c for c in player_data.columns if c.startswith("Gameweek")]

    for gd in gds_to_zero:
        if gd in player_data.columns:
            player_data[gd] = np.where(
                player_data["id"].isin(ids_to_zero), 0, player_data[gd]
            )
        else:
            print(f"Warning: {gd!r} in gds_to_zero is not a column in the EV sheet")

    # Average EV over the gamedays a player actually features on, so someone
    # whose team plays twice is not punished against someone who plays four
    # times when the value cutoff is applied.
    ev_across = player_data[pt_cols].replace(0, np.nan).mean(axis=1).fillna(0)
    value = ev_across / player_data["now_cost"]

    print(f"Players before value cutoff: {len(player_data)}")
    player_data = player_data[
        (value >= value_cutoff)
        | (player_data["id"].isin(in_team))
        | (player_data["id"].isin(locked))
    ]
    print(f"Players after value cutoff: {len(player_data)}")

    if in_team_sell_price:
        print("\nApplying selling prices...")
        sell_price_map = {p[0]: p[1] for p in in_team_sell_price}

        def apply_sell_price(row):
            if row["id"] in sell_price_map:
                return sell_price_map[row["id"]]
            return row["now_cost"]

        player_data["now_cost"] = player_data.apply(apply_sell_price, axis=1)

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


def is_mou_sheet(ev_sheet):
    return not ev_sheet or str(ev_sheet).strip().lower() in ("mou", "mou.csv")


def should_refresh_ev(ev_sheet, static, first_gw, first_gd, final_gw, final_gd):
    mode = str(refresh_ev).strip().lower()

    if mode in ("false", "none", "no", ""):
        return False

    if not is_mou_sheet(ev_sheet):
        # your own sheet, so rebuilding mou.csv would not be what you solve
        print(f"Not rebuilding the EV sheet: ev_sheet is {ev_sheet!r}, not mou")
        return False

    if mode != "auto":
        return True

    # "auto": only when the sheet is missing or does not reach the horizon
    path = DATA_DIR / "mou.csv"
    if not path.exists():
        print("No mou.csv yet, rebuilding it")
        return True
    try:
        columns = pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns
    except Exception:
        return True
    wanted = horizon_columns(static, first_gw, first_gd, final_gw, final_gd)
    missing = [c for c in wanted if c not in columns]
    if missing:
        print(
            f"mou.csv is missing {len(missing)} of {len(wanted)} gamedays, rebuilding"
        )
        return True
    print("mou.csv already covers the horizon, keeping it")
    return False


def run_mou_ev():
    """Rebuild data/mou.csv by running mou_ev.py as its own process.

    It is a script rather than a module (everything happens at import), so it
    cannot just be called, and a separate process keeps its scraping away from
    the solve.
    """
    script = Path(__file__).parent / "mou_ev.py"
    print(f"\n=== Rebuilding the EV sheet: {script.name} ===")
    result = subprocess.run([sys.executable, str(script)], cwd=str(script.parent))
    if result.returncode != 0:
        raise SystemExit(
            f"{script.name} failed with exit code {result.returncode}, so the EV "
            "sheet was not rebuilt. Fix that, or set 'refresh_ev' to false to "
            "solve off the existing sheet."
        )
    print("=== EV sheet rebuilt ===\n")


def read_ev_sheet(ev_sheet):
    # "mou" (or blank) is the sheet mou_ev.py writes; any other value is the
    # name of your own sheet in the data folder.
    name = "mou" if not ev_sheet else str(ev_sheet)
    if not name.endswith(".csv"):
        name += ".csv"
    path = DATA_DIR / name

    if not path.exists():
        raise FileNotFoundError(
            f"No EV sheet at {path}. Run 'python mou_ev.py' to build mou.csv, "
            "or point 'ev_sheet' at your own sheet in the data folder."
        )

    print(f"Loading EV from {name}")
    try:
        player_data = pd.read_csv(path, encoding="utf-8-sig", engine="python")
    except Exception:
        player_data = pd.read_csv(path, encoding="ISO-8859-1", engine="python")

    for col in ("id", "element_type"):
        player_data[col] = (
            pd.to_numeric(player_data[col], errors="coerce").fillna(0).astype(int)
        )

    return player_data[player_data["element_type"].isin([1, 2])]


def refresh_prices(player_data, player_info):
    # Prices move daily, so the costs baked into the EV sheet when it was built
    # go stale. Owned players get their real selling price applied later.
    if player_info is None:
        print("Skipping price refresh (info_source is not API)")
        return player_data

    live = player_info.set_index("id")["now_cost"]
    stale = player_data["id"].map(live)
    changed = int((stale.notna() & (stale != player_data["now_cost"])).sum())
    player_data["now_cost"] = stale.fillna(player_data["now_cost"]).astype(int)
    print(f"Refreshed prices from the API ({changed} changed since the EV sheet)")
    return player_data


# Each gameweek is exactly one "phcapt" phase: free transfers reset at the start
# of one, and the gameday captain can be used once within one. The game
# publishes the boundaries and they move every season, so they are never
# hardcoded here.
def transfer_periods_from_chips(static):
    periods = [
        {"start_event": c["start_event"], "stop_event": c["stop_event"]}
        for c in static.get("chips", [])
        if c.get("name") == "phcapt"
    ]
    return sorted(periods, key=lambda p: p["start_event"])


def period_containing(gameday, periods):
    for period in periods:
        if period["start_event"] <= gameday <= period["stop_event"]:
            return period
    return None


def detect_cap_used(chips_played, next_gd, periods):
    # The gameday captain is the "phcapt" chip and it can be played once per
    # gameweek, so it is spent if the entry already played one this gameweek.
    period = period_containing(next_gd, periods)
    if period is None:
        return False
    played = [
        x["event"] for x in chips_played if x.get("name") == "phcapt" and x.get("event")
    ]
    return any(period["start_event"] <= gd <= period["stop_event"] for gd in played)


_static_cache = {}


def get_static():
    if "data" not in _static_cache:
        _static_cache["data"] = requests.get(
            "https://nbafantasy.nba.com/api/bootstrap-static/"
        ).json()
    return _static_cache["data"]


def squad_total_spend(static=None):
    if static is None:
        try:
            static = get_static()
        except Exception:
            return 1000
    return static.get("game_settings", {}).get("squad_total_spend", 1000)


def read_calendar(static):
    """The season's gamedays, as {gameweek: [day, ...]} and {"2_3": gameday}.

    The gameday number is what the API calls an "event" and what chip windows
    are expressed in; the gameweek/day pair is what the settings and EV sheets
    use.
    """
    weeks = {}
    events = {}
    for e in static.get("events", []):
        nums = re.findall(r"(\d+)", e.get("name", ""))
        if len(nums) >= 2:
            week, day = int(nums[0]), int(nums[1])
            weeks.setdefault(week, []).append(day)
            events[f"{week}_{day}"] = e["id"]
    return {w: sorted(d) for w, d in weeks.items()}, events


def event_ids_by_day(static):
    return read_calendar(static)[1]


def next_gameday(static):
    """The gameweek and day of the next deadline."""
    for flag in ("is_next", "is_current"):
        event = next((x for x in static.get("events", []) if x.get(flag)), None)
        if event:
            nums = re.findall(r"(\d+)", event.get("name", ""))
            if len(nums) >= 2:
                return int(nums[0]), int(nums[1])
    return 1, 1


def parse_day(value, label):
    if not value:
        return None
    parts = str(value).strip().split("_")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(
            f'{label} must look like "2_3" for gameweek 2 day 3, got {value!r}'
        )
    return int(parts[0]), int(parts[1])


def resolve_horizon(static, horizon, start=None, end=None):
    """Turn "horizon": 3 into the range of gamedays to solve.

    The horizon counts gameweeks including whatever is left of the current one,
    so 3 on gameweek 1 day 2 runs to the end of gameweek 3. "start" and "end"
    override either edge when you want to plan from or to a specific gameday.
    """
    weeks, _ = read_calendar(static)
    if not weeks:
        raise ValueError("Could not read the gameweek calendar from the API")

    first_gw, first_gd = parse_day(start, "start") or next_gameday(static)

    try:
        horizon = int(horizon)
    except (TypeError, ValueError):
        raise ValueError(f"horizon must be a number of gameweeks, got {horizon!r}")
    if horizon < 1:
        raise ValueError(f"horizon must be at least 1, got {horizon}")

    if end:
        final_gw, final_gd = parse_day(end, "end")
    else:
        final_gw = min(first_gw + horizon - 1, max(weeks))
        final_gd = max(weeks.get(final_gw, [1]))

    for label, (week, day) in (
        ("start", (first_gw, first_gd)),
        ("end", (final_gw, final_gd)),
    ):
        if week not in weeks:
            raise ValueError(f"{label}: gameweek {week} is not in this season")
        if day not in weeks[week]:
            raise ValueError(
                f"{label}: gameweek {week} has days "
                f"{min(weeks[week])}-{max(weeks[week])}, not day {day}"
            )
    if (final_gw, final_gd) < (first_gw, first_gd):
        raise ValueError(
            f"end (GW{final_gw} Day{final_gd}) is before "
            f"start (GW{first_gw} Day{first_gd})"
        )

    days = [
        (w, d)
        for w in range(first_gw, final_gw + 1)
        for d in weeks[w]
        if (w, d) >= (first_gw, first_gd) and (w, d) <= (final_gw, final_gd)
    ]
    print(
        f"Horizon: Gameweek {first_gw} Day {first_gd} -> Gameweek {final_gw} "
        f"Day {final_gd} ({final_gw - first_gw + 1} gameweeks, {len(days)} gamedays)"
    )
    return first_gw, first_gd, final_gw, final_gd


def horizon_columns(static, first_gw, first_gd, final_gw, final_gd):
    weeks, _ = read_calendar(static)
    return [
        f"Gameweek {w} - Day {d}"
        for w in range(first_gw, final_gw + 1)
        for d in weeks.get(w, [])
        if (w, d) >= (first_gw, first_gd) and (w, d) <= (final_gw, final_gd)
    ]


def check_ev_coverage(player_data, static, first_gw, first_gd, final_gw, final_gd):
    wanted = horizon_columns(static, first_gw, first_gd, final_gw, final_gd)
    missing = [c for c in wanted if c not in player_data.columns]

    if len(missing) == len(wanted):
        raise ValueError(
            f"The EV sheet has no columns for the horizon ({wanted[0]} to "
            f"{wanted[-1]}). Run 'python mou_ev.py' to rebuild it."
        )
    if missing:
        print(
            f"Warning: the EV sheet is missing {len(missing)} of {len(wanted)} "
            f"gamedays in the horizon ({', '.join(missing[:3])}"
            f"{'...' if len(missing) > 3 else ''}). Those days will be skipped - "
            "run 'python mou_ev.py' to rebuild it."
        )


def get_chips_played():
    # [{"name": ..., "event": gameday}] for the chips this entry has used
    if no_team:
        return []
    try:
        if team_data == "json":
            with open("../data/team.json") as f:
                chips = json.load(f).get("chips", [])
            return [
                {"name": c.get("name"), "event": e}
                for c in chips
                for e in (c.get("played_by_entry") or [])
            ]
        history = requests.get(
            f"https://nbafantasy.nba.com/api/entry/{team_id}/history/"
        ).json()
        return history.get("chips", [])
    except Exception as e:
        print(f"Could not read played chips ({e}), assuming none used")
        return []


CHIP_LABELS = {"wc": ("wildcard", "Wildcard"), "as": ("rich", "All-Star")}


def validate_chips(static, chips_played, use_wc, use_as, limits):
    """Check the chip days in settings against what the game actually allows.

    Each chip lives in one or more windows of gamedays and can be played a set
    number of times within each. Planning one you do not have, or on a day
    outside its window, makes the whole solution unusable, so bail out early.
    """
    events = event_ids_by_day(static)
    limits = limits or {}
    problems = []

    for key, requested in (("wc", use_wc), ("as", use_as)):
        api_name, label = CHIP_LABELS[key]
        windows = sorted(
            (c for c in static.get("chips", []) if c.get("name") == api_name),
            key=lambda c: c["start_event"],
        )
        played = [
            c["event"]
            for c in chips_played
            if c.get("name") == api_name and c.get("event")
        ]
        days = [str(d).strip() for d in requested if str(d).strip()]

        unknown = [d for d in days if d not in events]
        if unknown:
            problems.append(
                f"{label}: {', '.join(unknown)} is not a gameday this season"
            )

        for window in windows:
            lo, hi = window["start_event"], window["stop_event"]
            used = sum(1 for e in played if lo <= e <= hi)
            planned = [d for d in days if d in events and lo <= events[d] <= hi]
            available = window.get("number", 1) - used
            if planned or used or len(windows) == 1:
                print(
                    f"  {label} gamedays {lo}-{hi}: {available} available "
                    f"({used} used), {len(planned)} planned"
                )
            if len(planned) > available:
                problems.append(
                    f"{label}: {len(planned)} planned in gamedays {lo}-{hi} "
                    f"({', '.join(planned)}) but {available} available"
                )

        outside = [
            d
            for d in days
            if d in events
            and not any(
                w["start_event"] <= events[d] <= w["stop_event"] for w in windows
            )
        ]
        if outside:
            problems.append(
                f"{label}: {', '.join(outside)} is outside every window the "
                f"{label.lower()} can be played in"
            )

        cap = limits.get(key)
        if cap is not None and len(days) > int(cap):
            problems.append(
                f"{label}: {len(days)} planned but chip_limits caps it at {cap}"
            )

    if problems:
        bullet = "\n  - "
        raise ValueError("Chip plan is not legal:" + bullet + bullet.join(problems))


def calculate_fts(transfers, next_gd, as_gds, wc_gds, transfer_periods):
    current_period = period_containing(next_gd, transfer_periods)
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


def fresh_squad(current_gw, static=None):
    # No squad to start from: the whole budget sits in the bank, the first
    # gameday is a free build, and two free transfers are available after it.
    budget = squad_total_spend(static)
    print(
        "No existing squad found - solving as a fresh squad build with a "
        f"budget of {budget / 10:.1f}"
    )
    return ([], [], False, 2, budget, current_gw)


def read_team_json(fallback_gw):
    current_gw = fallback_gw

    if no_team:
        return fresh_squad(current_gw)

    if team_data == "json":
        with open("../data/team.json") as f:
            d = json.load(f)
            in_team = [pick["element"] for pick in d["picks"]]
            in_team_sell_price = [
                [pick["element"], pick["selling_price"]] for pick in d["picks"]
            ]
            # my-team only lists the captain chip for the current gameweek,
            # so "played" means it is already spent
            cap_used = any(
                c.get("name") == "phcapt" and c.get("status_for_entry") == "played"
                for c in d.get("chips", [])
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

            next_event = next((x for x in static["events"] if x["is_next"]), None)
            curr_event = next((x for x in static["events"] if x["is_current"]), None)

            if next_event:
                next_gd = next_event["id"]
                current_gw = next_event["id"]
                picks_gw = next_event["id"] - 1
            elif curr_event:
                next_gd = curr_event["id"] + 1
                current_gw = curr_event["id"]
                picks_gw = curr_event["id"]
            else:
                next_gd = 1
                current_gw = 1
                picks_gw = 1

            if picks_gw < 1:
                picks_gw = 1

            player_db = {
                x["id"]: {
                    "now_cost": x["now_cost"],
                    "start_cost": x["now_cost"] - x["cost_change_start"],
                    "name": f"{x['first_name']} {x['second_name']}",
                    "element_type": x["element_type"],
                }
                for x in static["elements"]
            }

            history_url = f"{BASE_URL}/entry/{team_id}/history/"
            history_data = session.get(history_url).json()
            chips_list = history_data.get("chips", [])

            as_gds = [x["event"] for x in chips_list if x["name"] == "rich"]
            wc_gds = [x["event"] for x in chips_list if x["name"] == "wildcard"]

            transfers_url = f"{BASE_URL}/entry/{team_id}/transfers/"
            transfers = session.get(transfers_url).json()
            if not isinstance(transfers, list):
                # entry does not exist yet, so nothing has been transferred
                transfers = []

            transfer_periods = transfer_periods_from_chips(static)
            if transfer_periods:
                fts = calculate_fts(
                    transfers, next_gd, as_gds, wc_gds, transfer_periods
                )
                cap_used = detect_cap_used(chips_list, next_gd, transfer_periods)
            else:
                print(
                    "Warning: could not read the gameweek phases from the API, "
                    "assuming a fresh gameweek (2 free transfers, captain unused)"
                )
                fts = 2
                cap_used = False

            print(
                f"Free transfers: {fts} | Gameday captain used this gameweek: "
                f"{cap_used}"
            )

            purchase_map = {pid: v["start_cost"] for pid, v in player_db.items()}

            for t in sorted(transfers, key=lambda x: x["time"]):
                purchase_map[t["element_in"]] = t["element_in_cost"]

            current_picks, in_bank = None, None
            for gd in (picks_gw, picks_gw - 1):
                if gd < 1:
                    continue
                picks_url = f"{BASE_URL}/entry/{team_id}/event/{gd}/picks/"
                picks_res = session.get(picks_url).json()
                if "picks" in picks_res and picks_res["picks"]:
                    current_picks = picks_res["picks"]
                    in_bank = picks_res["entry_history"]["bank"]
                    break

            if current_picks is None:
                # Before the first deadline of the season there is no squad yet
                return fresh_squad(current_gw, static)

            my_data = {"picks": []}

            for p in current_picks:
                pid = p["element"]
                p_data = player_db.get(pid, {})

                now_cost = p_data.get("now_cost", 0)
                pur_price = purchase_map.get(pid, p_data.get("start_cost", 0))
                etype = p_data.get("element_type", 2)

                if now_cost > pur_price:
                    profit = now_cost - pur_price
                    sell_price = pur_price + (profit // 2)
                else:
                    sell_price = now_cost

                if sell_price > now_cost:
                    sell_price = now_cost

                my_data["picks"].append(
                    {"element": pid, "selling_price": sell_price, "element_type": etype}
                )

        in_team = [pick["element"] for pick in my_data["picks"]]
        in_team_sell_price = [
            [pick["element"], pick["selling_price"]] for pick in my_data["picks"]
        ]

        transfers_left = fts

    return (in_team, in_team_sell_price, cap_used, transfers_left, in_bank, current_gw)


if __name__ == "__main__":
    main(
        info_source,
        value_cutoff,
        decay,
        horizon,
        horizon_start,
        horizon_end,
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
        ev_sheet,
    )
