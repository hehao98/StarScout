import pandas as pd

df2 = pd.read_csv('data/filtered_repos_downloads.csv')

df = pd.read_csv('data/fake_stars_complex_users.csv')

df['starred_at'] = pd.to_datetime(df['starred_at'])

df['month'] = df['starred_at'].dt.to_period('M')
df2['month'] = pd.to_datetime(df2['month']).dt.to_period('M')


def count_real_fake(group):
    real_count = (group['fake_acct'] == 'unknown').sum()
    fake_count = (group['fake_acct'] != 'unknown').sum()
    return pd.Series({'real': real_count, 'fake': fake_count})


grouped = df.groupby(['repo_name', 'month']).apply(
    count_real_fake).reset_index()

merged_df = pd.merge(grouped, df2[['repo_name', 'month', 'downloads']], on=[
                     'repo_name', 'month'], how='left')
merged_df['downloads'] = merged_df['downloads'].astype('Int64')
merged_df = merged_df[merged_df['month'] != '2024-07']
merged_df.to_csv('data/merged_star_and_downloads.csv', index=False)
