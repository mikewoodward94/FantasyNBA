import pandas as pd
import glob

read_day = "20_1"
print_top_n = 20

sims_path = '../sims/*.csv'
results = []
file_count = 0

for file in glob.glob(sims_path):
    temp = pd.read_csv(file)
    temp = temp[temp[read_day] == 1]
    temp = temp[['id','name']]
    file_count = file_count + 1
    results.append(temp)
    
results = pd.concat(results).value_counts().reset_index()
results.columns = [['id','name','percent']]

results['percent'] = 100*results[['percent']]/file_count

print(results.head(print_top_n))

    
    
