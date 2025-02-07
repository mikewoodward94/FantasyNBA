import pandas as pd
import pulp
import re
import xlsxwriter
import uuid

def nba_solver(data, locked, banned, gd_banned, wildcard, in_team, cap_used, transfers_left, in_bank, decay, gap, max_time, transfer_penalty):
    print("Setting up and starting solve")
    team_value = data[data['id'].isin(in_team)]['now_cost'].sum()
    money = team_value + in_bank    
    
    # remove banned players
    data = data[~data['id'].isin(banned)]    

    data = data.set_index('id')
    
    player_ids = data.index
    point_columns = data.columns[11:]

    # create dictionary of gameweeks + game days
    week_day_list = []
    week_day_dict = {}
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
    
    current_week = min(list(week_day_dict.keys()))
    current_day = min(list(week_day_dict[current_week]))
    
    in_team_flag = {id: 1 if id in in_team else 0 for id in player_ids}
    
    # create columns for team and position
    positions = pd.get_dummies(data, columns=['element_type'], prefix='pos')[['pos_1','pos_2']].astype(int)
    teams = pd.get_dummies(data, columns=['team'], prefix='team')
    teams = teams.loc[:, teams.columns.str.startswith('team_')].astype(int)

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
                points[a][b][i] = data[point_columns[position-1]][i]
                squad_var[a][b][i] = pulp.LpVariable('gwk' + str(a) + 'gdy' + str(b) +'x' + str(i), cat='Binary')
                team_var[a][b][i] = pulp.LpVariable('gwk' + str(a) + 'gdy' + str(b) +'y' + str(i), cat='Binary')
                cap_var[a][b][i] = pulp.LpVariable('gwk' + str(a) + 'gdy' + str(b) +'c' + str(i), cat='Binary')
                transfer_var[a][b][i] = pulp.LpVariable(f'transfer_gwk{a}_gdy{b}_x{i}', cat='Binary')
    
    # Start Problem
    prob = pulp.LpProblem("Optimiser", pulp.LpMaximize)
   
    # Objective Function
    prob += pulp.lpSum([((points[a][b][i] * team_var[a][b][i]) + (points[a][b][i] * cap_var[a][b][i]) - (transfer_var[a][b][i] * penalty_dict[a][b] * decay_dict[a][b])) for a in week_day_dict.keys() for b in week_day_dict[a] for i in player_ids])

    for a in week_day_dict.keys():
        
        if cap_used == True and a == current_week:
            prob += pulp.lpSum([cap_var[a][b][i] for b in week_day_dict[a] for i in player_ids]) == 0
        else:
            prob += pulp.lpSum([cap_var[a][b][i] for b in week_day_dict[a] for i in player_ids]) == 1
        
        for b in week_day_dict[a]:
            prob += pulp.lpSum([squad_var[a][b][i] for i in player_ids]) == 10
            prob += pulp.lpSum([team_var[a][b][i] for i in player_ids]) == 5
            prob +=  pulp.lpSum([data['now_cost'][i] * squad_var[a][b][i] for i in player_ids]) <= money
            prob +=  pulp.lpSum([positions['pos_1'][i] * team_var[a][b][i] for i in player_ids]) >= 2
            prob +=  pulp.lpSum([positions['pos_1'][i] * team_var[a][b][i] for i in player_ids]) <= 3
            prob +=  pulp.lpSum([positions['pos_1'][i] * squad_var[a][b][i] for i in player_ids]) == 5
            
            
            for team in teams:
                prob +=  pulp.lpSum([teams[team][i] * squad_var[a][b][i] for i in player_ids]) <= 2
            
            for i in player_ids:
                prob += team_var[a][b][i] <= squad_var[a][b][i]
                prob += cap_var[a][b][i] <= team_var[a][b][i]
        
    
    # Track transfers across days and weeks
    for a in week_day_dict.keys():
        for b in week_day_dict[a]:
            for i in player_ids:
                # Transfer event: 1 if the player was added or removed on this day, 0 otherwise
                
                # Transfer check within the same week (compare with the previous day in the same week)
                if a == current_week and b == current_day and wildcard == True:
                    prob += transfer_var[a][b][i] == 0
                elif a == current_week and b == current_day and wildcard == False:
                    prob += transfer_var[a][b][i] >= squad_var[a][b][i] - in_team_flag[i]
                elif b > 1:
                    current_index = week_day_dict[a].index(b)
                    previous_day = week_day_dict[a][current_index - 1]
                    prob += transfer_var[a][b][i] >= squad_var[a][b][i] - squad_var[a][previous_day][i]
                else:
                    # For the first day of the new week, compare with the last day of the previous week
                    if a > current_week:
                        last_day_of_prev_week = max(week_day_dict[a-1])
                        prob += transfer_var[a][b][i] >= squad_var[a][b][i] - squad_var[a-1][last_day_of_prev_week][i]
                    else:
                        # For the very first week, no transfers should have occurred before
                        prob += transfer_var[a][b][i] == 0
                        
            
        
        if a > current_week:
            prob += pulp.lpSum([transfer_var[a][b][i] for b in week_day_dict[a] for i in player_ids]) <= 2
        else:
            prob += pulp.lpSum([transfer_var[a][b][i] for b in week_day_dict[a] for i in player_ids]) <= transfers_left
    
    
    for i in locked:
        prob += squad_var[current_week][current_day][i] == 1
            
    
    if wildcard == False:
        prob += pulp.lpSum([squad_var[current_week][current_day][i] for i in in_team]) >= 8
    
    prob += pulp.lpSum([squad_var[current_week][current_day][i] for i in gd_banned]) == 0
    
   
    prob.solve(pulp.HiGHS(timeLimit=max_time, gapRel=gap))
    print("Score: ", pulp.value(prob.objective))
    print("Status: ", pulp.LpStatus[prob.status])
    
    # Create Output Excel
    
    output = data[['name', 'now_cost']].reset_index()
    
    squad = {i: {j: {} for j in week_day_dict[i]} for i in week_day_dict.keys()}
    team = {i: {j: {} for j in week_day_dict[i]} for i in week_day_dict.keys()}
    cap = {i: {j: {} for j in week_day_dict[i]} for i in week_day_dict.keys()}
            
    for a in week_day_dict.keys():
        for b in week_day_dict[a]:
            for i in player_ids:
                squad[a][b][i] = round(squad_var[a][b][i].varValue)
                team[a][b][i] = round(team_var[a][b][i].varValue)
                cap[a][b][i] = round(cap_var[a][b][i].varValue)
    
    flattened_dict = {}

    for outer_key, inner_dict in squad.items():
        for inner_key, value_dict in inner_dict.items():
            new_key = f"{outer_key}_{inner_key}"
            for value_key, value in value_dict.items():
                if value_key not in flattened_dict:
                    flattened_dict[value_key] = {}
                flattened_dict[value_key][new_key] = value

  
    squad_df = pd.DataFrame(flattened_dict)
    squad_df = squad_df.T
    squad_df.reset_index(inplace=True)
    squad_df.rename(columns={'index': 'id'}, inplace=True)
    squad_df = pd.merge(output, squad_df, on=['id'], how='right')
    squad_df = squad_df[squad_df.iloc[:,3:].eq(1).any(axis=1)]  
    squad_df['current'] = squad_df['id'].map(in_team_flag)
    
    flattened_dict = {}

    for outer_key, inner_dict in team.items():
        for inner_key, value_dict in inner_dict.items():
            new_key = f"{outer_key}_{inner_key}"
            for value_key, value in value_dict.items():
                if value_key not in flattened_dict:
                    flattened_dict[value_key] = {}
                flattened_dict[value_key][new_key] = value

  
    team_df = pd.DataFrame(flattened_dict)
    team_df = team_df.T
    team_df.reset_index(inplace=True)
    team_df.rename(columns={'index': 'id'}, inplace=True)
    team_df = pd.merge(output, team_df, on=['id'], how='right')
    team_df = team_df[team_df.iloc[:,3:].eq(1).any(axis=1)]  
    
    flattened_dict = {}

    for outer_key, inner_dict in cap.items():
        for inner_key, value_dict in inner_dict.items():
            new_key = f"{outer_key}_{inner_key}"
            for value_key, value in value_dict.items():
                if value_key not in flattened_dict:
                    flattened_dict[value_key] = {}
                flattened_dict[value_key][new_key] = value

  
    cap_df = pd.DataFrame(flattened_dict)
    cap_df = cap_df.T
    cap_df.reset_index(inplace=True)
    cap_df.rename(columns={'index': 'id'}, inplace=True)
    cap_df = pd.merge(output, cap_df, on=['id'], how='right')
    cap_df = cap_df[cap_df.iloc[:,3:].eq(1).any(axis=1)]  
    
    
    writer = pd.ExcelWriter('../output/NBA_Squad.xlsx', engine = 'xlsxwriter')
    squad_df.to_excel(writer, sheet_name = 'Squad', index=False)
    team_df.to_excel(writer, sheet_name = 'Team', index=False)
    cap_df.to_excel(writer, sheet_name = 'Cap', index=False)
    writer.close()
    print("Squad and Transfer Plan output to NBA_Squad.xlsx")
    
