import requests
import pandas as pd
import numpy as np
import json
import re

from solver import nba_solver

# EV Settings
decay = 0.97
home = 1.02
away = 0.98
value_cutoff = 0.25
transfer_penalty = {
    1: 15,
    2: 15,
    3: 10,
    4: 5,
    5: 5,
    6: 0,
    7: 0
}

# Gameday Range
first_gd = 4
first_gw = 16
final_gd = 4
final_gw = 18

# Player Settings
locked = []
banned = []
gd_banned = []

# Chip Settings
wildcard = False

# Solver Settings
max_time = 3600
gap = 0.0
info_source = 'API'

def main(info_source, value_cutoff, decay, home, away, first_gd, first_gw, final_gw, final_gd, locked, banned, gd_banned, wildcard, gap, max_time, transfer_penalty):
    if info_source == 'API':
        # Get From API
        print("Retrieving player and fixture data from Fantasy NBA API")
        player_info = get_player_info()
        player_info.to_csv('../data/player_info.csv', index=False)
        
        fixture_info = get_fixture_info(player_info)
        fixture_info = clean_fixture_info(fixture_info)
        fixture_info.to_csv('../data/fixtures.csv', index = False)
    
    print("Generating EV")
    in_team, in_team_sell_price, cap_used, transfers_left, in_bank = read_team_json()
    
    player_info = pd.read_csv('../data/player_info.csv')
    player_info = player_info[(player_info['status'].isin(['a','d'])) | (player_info['id'].isin(in_team))]
   
    hashtag_data = read_hashtag()
    
    player_data = player_info.merge(hashtag_data,left_on='name',right_on='PLAYER',how='inner')
    player_data = player_data[['id','name','team','now_cost','element_type','PTS','TREB','AST','STL','BLK','TO','PPG']]
    
    for p_id, selling_price in in_team_sell_price:
        player_data['now_cost'] = np.where(player_data['id'] == p_id, selling_price, player_data['now_cost'])
    
    fixtures = read_fixtures(first_gd, first_gw, final_gw, final_gd)
    player_data = player_data.merge(fixtures, on='id', how='inner')
    
    team_def_strength = read_team_def_strength()
    def_rating_dict = team_def_strength.set_index('TEAM').T.to_dict('list')
    
    location_dict = {'home': home, 'away': away}
    
    player_data = replace_with_value(player_data, location_dict, def_rating_dict)
    
    print(f'Players before value cutoff: {len(player_data)}')
    player_data['value'] = player_data['PPG']/player_data['now_cost']
    
    player_data = player_data[(player_data['value'] >= value_cutoff) | (player_data['id'].isin(in_team)) | (player_data['id'].isin(locked))]
    player_data = player_data.drop(columns=['value'])
    print(f'Players after value cutoff: {len(player_data)}')

    player_data = apply_decay(player_data, decay)
    
    player_data.to_csv('../output/NBA_EV.csv', index=False)
    print("EV generated and output to NBA_EV.csv")
    nba_solver(player_data, locked, banned, gd_banned, wildcard, in_team, cap_used, transfers_left, in_bank, decay, gap, max_time, transfer_penalty)
    
    
def get_player_info():
    
    url = "https://nbafantasy.nba.com/api/bootstrap-static/"
    r = requests.get(url)
    json = r.json()
    elements = pd.DataFrame(json['elements'])
    elements = elements[['id',
                         'first_name',
                         'second_name',
                         'now_cost',
                         'team',
                         'element_type',
                         'status'
                         ]]
    elements['name'] = elements['first_name'] + ' ' + elements['second_name']
    
    elements = elements[['id',
                         'name',
                         'now_cost',
                         'team',
                         'element_type',
                         'status'
                         ]]
    return(elements)

def get_fixture_info(player_info):
    
    fixtures = []
    
    for i in player_info['id']:
        url = "https://nbafantasy.nba.com/api/element-summary/"+str(i)+"/"
        r = requests.get(url)
        json = r.json()
        if json == {'detail': 'Not found.'}:
            continue
        else:
            data=pd.DataFrame(json['fixtures'])
            data["id"] = i
            data=data[["team_h", "team_a", "event_name", "is_home", "id"]]
            fixtures.append(data)

    fixtures=pd.concat(fixtures)
    
    return(fixtures)

def clean_fixture_info(fixture_info):
    
    fixture_info['opp_team'] = np.where(fixture_info['is_home'] == True, fixture_info['team_a'], fixture_info['team_h'])
    fixture_info['location'] = np.where(fixture_info['is_home'] == True, 'home','away')
    fixture_info = fixture_info[['id','event_name','location','opp_team']]
    fixture_info = fixture_info.dropna()
    
    return(fixture_info)

def read_hashtag():
    
    data = pd.read_csv('../data/hashtag_season.csv')
    data = data[[
                'PLAYER',
                'PTS',
                'TREB',
                'AST',
                'STL',
                'BLK',
                'TO'
                ]]
    
    data = data[data['PLAYER'] != 'PLAYER']
    
    cols = ['PTS','TREB','AST','STL','BLK','TO']
    data[cols] = data[cols].apply(pd.to_numeric, errors='coerce')
    
    multiplier = [1, 1.2, 1.5, 3, 3, -1]
    data[cols] = data[cols] * multiplier
    data['PPG'] = data[cols].sum(axis=1)
    return(data)

def read_fixtures(first_gd, first_gw, final_gw, final_gd):
    
    fixtures = pd.read_csv('../Data/fixtures.csv')
    fixtures['gameweek'] = fixtures['event_name'].str.findall('(\d+)').str[0].astype(int)
    fixtures['gameday'] = fixtures['event_name'].str.findall('(\d+)').str[1].astype(int)
    
    fixtures = fixtures[fixtures['gameweek'] <= final_gw]
    fixtures = fixtures[fixtures['gameweek'] >= first_gw]
    fixtures = fixtures[(fixtures['gameweek'] > first_gw) | (fixtures['gameday'] >= first_gd)]
    fixtures = fixtures[(fixtures['gameweek'] < final_gw) | (fixtures['gameday'] <= final_gd)]
    
    
    fixtures = fixtures[['id','event_name','location','opp_team']]
    
    team_ids = pd.read_csv('../data/team_ids.csv')
    fixtures = fixtures.merge(team_ids, left_on='opp_team', right_on='team_id')

    fixtures['info'] = fixtures.apply(lambda x: [x['location'], x['team']], axis=1)

    fixtures = fixtures[['id','event_name','info']]
    
    cols = sorted(fixtures['event_name'].unique(), key=lambda x: (
        int(x.split()[1]),
        int(x.split()[-1])
        ))
    
    fixtures = fixtures.pivot(index='id', columns='event_name', values='info')
    fixtures = fixtures[cols]
    
    fixtures = fixtures.fillna('').reset_index()
    
    return(fixtures)

def read_team_def_strength():

    data = pd.read_csv('../Data/team_def_data_2425.csv')    
    data_cols = ['PTS','REB','AST','STL','BLK','TOV']
    
    for col in data_cols:
        mean = data[col].mean()
        data[f'{col}_rating'] = data[col]/mean
    
    data = data[['TEAM','PTS_rating','REB_rating','AST_rating','STL_rating','BLK_rating','TOV_rating']]
    
    return(data)
    
def replace_with_value(player_data, location_dict, def_rating_dict):
    
    game_cols = player_data.columns[12:].to_list()
    
    for col in game_cols:
        player_data[col] = player_data[col].apply(lambda x: replace_values(x, location_dict))
        player_data[col] = player_data[col].apply(lambda x: replace_values(x, def_rating_dict))
        player_data[col] = player_data.apply(transform_gameday, axis=1, col=col)
        player_data[col] = player_data[col].apply(multiply_list)
        
    return(player_data)
    
def replace_values(lst, mapping):
    return [mapping.get(item, item) for item in lst]    

def transform_gameday(row,col):
    
    if not row[col]:
        return[0, 0]
    
    location = row[col][0] 
    action_list = row[col][1]  
    multiplied_values = [action_list[0] * row['PTS'],
                         action_list[1] * row['TREB'],
                         action_list[2] * row['AST'],
                         action_list[3] * row['STL'],
                         action_list[4] * row['BLK'],
                         action_list[5] * row['TO']]
    total = sum(multiplied_values)
    return [location, total]

def multiply_list(lst):

    return np.prod(lst)  

def apply_decay(player_data, decay_factor):
    
    week_day_list = []
    week_day_dict = {}
    
    point_columns = [x for x in player_data.columns if 'Gameweek' in x]
    
    for col in point_columns:
        week = int(re.findall('(\d+)',col)[0])
        day = int(re.findall('(\d+)',col)[1])
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
                decay *= decay_factor  
    return(player_data)
   
def read_team_json():
    
    with open('../data/team.json') as f:
        d = json.load(f)
        
        in_team = [pick["element"] for pick in d["picks"]]
        in_team_sell_price = [[pick["element"], pick["selling_price"]] for pick in d["picks"]]
        cap_used = any(chip["name"] == "phcapt" and chip["status_for_entry"] in ["played"] for chip in d["chips"])
        transfers_left = 2 - d["transfers"]["made"]
        in_bank = d["transfers"]["bank"]
        
    return(in_team, in_team_sell_price, cap_used, transfers_left,in_bank)

if __name__ == '__main__':
    main(info_source, value_cutoff, decay, home, away, first_gd, first_gw, final_gw, final_gd, locked, banned, gd_banned, wildcard, gap, max_time, transfer_penalty)
