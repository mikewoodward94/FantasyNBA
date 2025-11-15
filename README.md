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
Please run the following to ensure that you have all prerequisite packages installed:
```
pip install -r requirements.txt
```
### Running the Code

After you've done this navigate to the `code` folder: 
```
cd code
```
and run run_solve.py: 
```
python run_solve.py
```
and it *should* all work.

Solved csvs can be found in the `output` folder following a successful run.

## Data
Player data in the repository is taken from Hashtag Basketball (as of 6/2/25), if you'd like to update this you can replace the content in hashtag_Season.csv by copying and pasting from here: https://hashtagbasketball.com/fantasy-basketball-rankings

Team defensive data in the repository is taken from the official NBA stats site (as of 6/2/25), if you'd like to update this you can replace the content in team_def_data_2425.csv by copying and pasting from here (important that it's PER GAME): https://www.nba.com/stats/teams/opponent

When you first run the code it will pull player information (Cost, Injury Status, etc) and Fixture information from the Fantasy NBA API, this also generates CSVs and you can change the setting "info_source" to be blank if you don't want to refresh these and save time.

Thanks to Mou, you can now generate a dynamically updated EV sheet running the `mou_ev.py` file (just run `cd code` followed by `python mou_ev.py` and wa) to get the `mou.csv` in your data folder. To determine the horizon of the csv, simply set `gws_to_run` in the file to your liking (the days shall adjust accordingly).

## Settings
You can find default settings in data/settings.json
### EV Settings
**Note**:  These settings only tweak the generation of EV using the hashtag data, does not alter the mou EV.

`decay`: How much EV is decayed by Game Day.

`home`: Home advantage EV boost.

`away`: Away disadvantage EV "boost".

`value_cutoff`: Average EV Divided by Player Cost threshold to be included in solve.

`transfer_penalty`: Dictionary of EV penalty applied if transfer occurs on that Gameday.

### Gameday Range
Here you set the range of gamedays that you would like to solve between (inclusive).

I normally solve for 3 gameweeks at a time, which is usually 21 gamedays.

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

`gw_cap_used`: Needed only if setting team_data as id, set as true if gameday captain already used for the current GW.

### Solver Settings
`num_iterations`:  The nuumber of different solutions to be generated, the criteria is controlled by `iteration_criteria`.

`iteration_criteria`: The rule which dictates as to how the solutions are differentiated from each other:
   - `this_day_transfer_in` will force to replace players to buy current day in each solution;
   - `this_day_transfer_out` will force to replace players to sell current day in each solution;
   - `this_day_transfer_in_out` will force to replace players to buy or sell current day in each solution;
   - `this_day_lineup` will force to replace at least N players in your lineup (only criteria which uses `iteration_difference`).

`iteration_difference`: Number of players to be different across the iterations.

`max_time`: Max time in seconds to allow for solve.

`gap`: Optimality Gap.

`info_source`: Default is "API", but make this blank if you just want it to pull from saved CSVs.

`team_data`: Set as "json" if you prefer the team.json else stick to "id".

`team_id`: Your team id can be derived your points page URL or your rank history URL.

`ev_sheet`: Set as true if you wish to the already created csv or have your own (ensure that it is in the data folder) or if you are using the `mou.csv`, just set it as `ev_sheet="mou"`.

### Output
`print_transfer_chip_summary`: whether you want the transfer chip summary to be printed to the screen (Gameweek 2 - Day 2: Roll, Gameweek 2 - Day 3: (Wildcard) PayerA -> PlayerB, ....).

`print_squads`: Whether you want the lineup and bench printed for each gameweek in your solution.

`print_result_table`: Whether you want the result table printed to the screen after the solve has finished (the table with iter,buy,sell, chip, score columns)

`export_excel`: If you wish for the solution to be saved as an excel sheet in `data/results` folder.

