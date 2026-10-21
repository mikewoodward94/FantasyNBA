# FantasyNBA
EV Generator and Squad Solver for Fantasy NBA (Salary Cap Edition)

Sign up and play here: https://nbafantasy.nba.com/

## Join My League!
Click here to auto join: https://nbafantasy.nba.com/leagues/auto-join/4qx9qw

## Important Instructions
### team.json
Replace the team.json found in the data file with that of your own team!

You can find this here: https://nbafantasy.nba.com/api/my-team/{YOUR_ID}/

You must be logged in, and you can find your ID in the url if you navigate to your gameday history.

P.S. You can run a solve by just plugging in your id in the settings.json

### Installing Requirements
Run the code to clone (i.e. install it locally) the repository:

```
git clone https://github.com/mikewoodward94/FantasyNBA.git
```

Please run the following to ensure that you have all prerequisite packages installed to run solves hassle-free:
```
pip install -r requirements.txt
```
### Running the Code
One command:

```
cd code
python run_solve.py
```

That rebuilds the EV projections and then solves, so there is nothing to run in
order and nothing to keep in step. Solved squads land in the `output` folder as
xlsx.

`run_solve.py` is the only entry point. `mou_ev.py` builds the EV projections
and `run_solve.py` runs it for you, though you can still run it on its own if
you only want to refresh `data/mou.csv`. `solver.py` is a library holding the
optimisation model, imported by `run_solve.py` - you never run it directly.

Rebuilding the projections is the slow part, because it scrapes EPM data and
the injury report. When you are trying out solver settings rather than chasing
fresh numbers, set `refresh_ev` to `false` (or `"auto"`) to reuse the sheet you
already have.

## Data
EV comes from `mou_ev.py` (thanks to Mou), which projects every player's
expected points from Dunks and Threes EPM data plus the current injury report,
and writes `data/mou.csv`. `run_solve.py` runs it for you, so you do not need
to invoke it yourself. The gameweeks it projects come from `horizon` in
settings.json (see below), the same setting the solver uses, so the sheet and
the solve always cover the same gamedays.

Every solve also pulls current player data from the Fantasy NBA API and
rewrites `data/player_info.csv`, then refreshes the prices in the EV sheet from
it, because prices move daily and the costs baked into `mou.csv` go stale as
soon as it is a day old. Set `info_source` to blank to skip that and use the
sheet's own prices.

Scoring weights are read from the game's own API rather than hardcoded. For
2026/27 that is 1 per point, 1 per rebound, 2 per assist, 3 per steal and 3 per
block, with turnovers no longer scored at all.

## Settings
You can find default settings in data/settings.json
### EV Settings
`decay`: How much EV is decayed by Game Day.

`value_cutoff`: Average EV Divided by Player Cost threshold to be included in solve.

`transfer_penalty`: Dictionary of EV penalty applied if transfer occurs on that Gameday.

### Horizon
`horizon`: How many gameweeks to solve, counting whatever is left of the
current one. `3` on gameweek 1 day 2 means gameweek 1 day 2 through the end of
gameweek 3. This is normally the only thing you change between solves, and it
sets the range for both `mou_ev.py` and `run_solve.py`, so the EV sheet and the
solve always cover the same gamedays. It clamps at the end of the season.

`start`: `null` means the next deadline, which is what you want almost always.
Set it to a gameday like `"2_3"` (gameweek 2, day 3) to plan from a specific
point instead.

`end`: `null` means the last day of the last gameweek in the horizon. Set it to
a gameday like `"3_4"` to stop part way through a gameweek.

`refresh_ev`: Whether `run_solve.py` rebuilds the EV projections before solving.
`true` (the default) always rebuilds, so a solve is always on current numbers.
`false` never does, which is what you want when you are iterating on solver
settings and do not want to wait for the scrape. `"auto"` rebuilds only when
`data/mou.csv` is missing or does not reach the horizon. Either way, if the
sheet does not cover the gamedays being solved, the run tells you rather than
quietly solving a shorter range.

### Player Settings
`locked`: List of IDs to lock in team.

`banned`: List of IDs to ban from team.

`gd_banned`: List of IDs to ban from team for only next Gameday.

`gds_to_zero`: List of days to zero out for player(s) listed in `ids_to_zero`.

`ids_to_zero`:  List of player IDs to be zeroed out on specific days.

`booked_transfers`: Allows you to force future transactions during specific days. For instance, if you wish to transfer out Anthony Davis (ID: 134) in GW2 Day 2, use `booked_transfers": [{"gw": 2, "day":2, "transfer_out": 134}]`. If you have a the replacement in mind too, say Mark Williams (ID: 469), you can add his id in the same dict with the key "transfer_in". So it will be like `booked_transfers": [{"gw": 2, "day":2, "transfer_in":469, "transfer_out": 134}]`. Both transfer_in and transfer_out can be null (it's assumed null if not entered). They do not clash with iterations either and work along with your wc/allstar solves too.

### Chip Settings
`use_wc`: List of GWs to use wildcard. Days need to be entered as week_day in strings so: `use_wc: ["2_3"]`  would imply a wc in GW2 Day 3. Can use multiple of them too, `use_wc: ["2_3", "2_5"]`.

`use_as`: List of GWs to use allstar in. Days need to be entered as week_day in strings so: `use_as: ["2_3"]`  would imply an as in GW2 Day 3. Can use multiple of them too, `use_as: ["2_3", "2_5"]`.

`day_solve`: Choose to solve just the allstar day (True) or a normal solve ignoring that day (False).

`chip_limits`: Caps how many of each chip the plan may use, as `{"wc": 1, "as": 0}`. Leave it as `null` and the only limits are the game's own. Either way the days in `use_wc` and `use_as` are checked against what the game actually allows before the solve starts: each chip's windows of gamedays, how many it allows per window, and which ones you have already played. An illegal plan stops the run rather than producing a solution you cannot enter.

**Gameday captain**: there is no setting for this. Whether the captain has already been used this gameweek is read from the chips your entry has played (it is the `phcapt` chip, one per gameweek), so there is nothing to remember or reset.

### Solver Settings
`num_iterations`:  The nuumber of different solutions to be generated, the criteria is controlled by `iteration_criteria`.

`iteration_criteria`: The rule which dictates as to how the solutions are differentiated from each other:
   - `this_day_transfer_in` will force to replace players to buy current day in each solution;
   - `this_day_transfer_out` will force to replace players to sell current day in each solution;
   - `this_day_transfer_in_out` will force to replace players to buy or sell current day in each solution;
   - `this_day_lineup` will force to replace at least N players in your lineup (only criteria which uses `iteration_difference`).

`iteration_difference`: Number of players to be different across the iterations.

`weekly_hit_limit`: Restricts the amount of hits that solver considers in a week (for instance, setting it to `weekly_hit_limit=1` would ensure that the solver **considers** only a singular hit every gameweek). Set to `0` if you want no hits **considered** whatsoever or to `""` if you have no preference as such.

`hit_cost`: Set at `100` by default, can be tailored to your own *perception* of the cost of a points hit.

`max_time`: Max time in seconds to allow for solve.

`gap`: Optimality Gap.

`info_source`: Default is "API", but make this blank if you just want it to pull from saved CSVs.

`team_data`: Set as "json" if you prefer the team.json else stick to "id".

`team_id`: Your team id can be derived your points page URL or your rank history URL.

`no_team`: Set as true to solve from scratch with no starting squad (the full 100.0 budget in the bank, all 10 picks free). This is detected automatically before the first deadline of the season, so you only need the setting if you want to force a fresh build at any other point.

`ev_sheet`: Which EV sheet to solve from. `"mou"` (the default, and what you get if you leave it blank) is the `mou.csv` that `mou_ev.py` writes. Set it to the name of any other csv in the data folder to use your own sheet instead; it needs `id`, `name`, `team`, `now_cost`, `element_type` and a `Gameweek X - Day Y` column per gameday.

### Output
`print_transfer_chip_summary`: whether you want the transfer chip summary to be printed to the screen (Gameweek 2 - Day 2: Roll, Gameweek 2 - Day 3: (Wildcard) PayerA -> PlayerB, ....).

`print_squads`: Whether you want the lineup and bench printed for each gameweek in your solution.

`print_result_table`: Whether you want the result table printed to the screen after the solve has finished (the table with iter,buy,sell, chip, score columns)

`export_excel`: If you wish for the solution to be saved as an excel sheet in `data/results` folder.

