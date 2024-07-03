import pandas as pd

# Load the first CSV file and filter it
file_path1 = 'data/fake_stars_obvious_percentage.csv'
df1 = pd.read_csv(file_path1)
filtered_df1 = df1[(df1['fake_percentage'] >= 2) | (df1['fake_stars'] >= 100)]

# Load the second CSV file
file_path2 = 'data/fake_stars_obvious_users.csv'
df2 = pd.read_csv(file_path2)

# Filter out rows in df2 where the 'github' column matches any in filtered_df1
filtered_df2 = df2[df2['github'].isin(filtered_df1['github'])]

filtered_df1.to_csv('data/filtered_repos_percentage.csv', index=False)
filtered_df2.to_csv('data/filtered_repos_users.csv', index=False)
