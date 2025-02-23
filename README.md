# FantasyNBA
EV Generator and Squad Solver for Fantasy NBA (Salary Cap Edition)

Sign up and play here: https://nbafantasy.nba.com/

## Join My League!
Click here to auto join: https://nbafantasy.nba.com/leagues/auto-join/dtbzi7

## Important Instructions
### team.json
Replace the team.json found in the data file with that of your own team!

You can find this here: https://nbafantasy.nba.com/api/my-team/{YOUR_ID}/

You must be logged in, and you can find your ID in the url if you navigate to your gameday history.

### HiGHS
This solver uses HiGHS, make sure you have it downloaded and included in Path.

Can be downloaded here: https://github.com/JuliaBinaryWrappers/HiGHSstatic_jll.jl

### Running the Code

After you've done this navigate to the code folder and run run_solve.py and it *should* all work.

EV and Solve will be found in the output folder following successful run.

## Data
Player data in the repository is taken from Hashtag Basketball (as of 6/2/25), if you'd like to update this you can replace the content in hashtag_Season.csv by copying and pasting from here: https://hashtagbasketball.com/fantasy-basketball-rankings

Team defensive data in the repository is taken from the official NBA stats site (as of 6/2/25), if you'd like to update this you can replace the content in team_def_data_2425.csv by copying and pasting from here (important that it's PER GAME): https://www.nba.com/stats/teams/opponent

When you first run the code it will pull player information (Cost, Injury Status, etc) and Fixture information from the Fantasy NBA API, this also generates CSVs and you can change the setting "info_source" to be blank if you don't want to refresh these and save time.

## Settings
You can find default settings in run_solve.py
### EV Settings
decay: How much EV is decayed by Game Day

home: Home advantage EV boost

away: Away disadvantage EV "boost"

value_cutoff: Average EV Divided by Player Cost threshold to be included in solve.

transfer_penalty: Dictionary of EV penalty applied if transfer occurs on that Game Day.

### Gameday Range
Here you set the range of gamedays that you would like to solve between (inclusive).

I normally solve for 3 gameweeks at a time, which is usually 21 gamedays.

### Player Settings
locked: List of IDs to lock in team

banned: List of IDs to ban from team

gd_banned: List of IDs to ban from team for only next Game Day

### Chip Settings
wildcard: Use wildcard (True or False)

allstar: Use allstar (True or False)

day_solve: Choose to solve just the allstar day (True) or a normal solve ignoring that day (False)

allstar_day: The gameday that allstar chip is used on i.e. "Gameweek 20 - Day 1"

### Solver Settings
max_time: Max time in seconds to allow for solve.

gap: Optimality Gap

info_source: Default is "API", but make this blank if you just want it to pull from saved CSVs.
