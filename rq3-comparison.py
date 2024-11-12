import json
import pandas as pd
from PIL import Image
import requests
import time
from io import BytesIO
from scripts import GITHUB_TOKENS
import logging
import sys
token = GITHUB_TOKENS[0]
headers = {
    'Authorization': f'token {token}'
}


def is_image_default(URL):
    response = requests.get(URL, headers=headers)
    if response.status_code == 403:  # 403 Forbidden due to rate limit
        rate_limit_reset = int(response.headers.get(
            'X-RateLimit-Reset', time.time() + 3600))
        # Sleep until the reset time or 1 hour
        sleep_time = max(rate_limit_reset - int(time.time()), 3600)
        logging.info(
            f"Rate limit exceeded in is_image_default(). Sleeping for {sleep_time} seconds...")
        time.sleep(sleep_time)
        return is_image_default(URL)  # Retry after sleeping
    img = Image.open(BytesIO(response.content))
    unique_colors = set()
    for i in range(img.size[0]):
        for j in range(img.size[1]):
            pixel = img.getpixel((i, j))
            unique_colors.add(pixel)
    if img.size[0] == 420 and img.size[1] == 420 and len(unique_colors) == 2:
        return True
    return False


def has_organization(URL):
    response = requests.get(URL, headers=headers)
    if response.status_code == 403:  # 403 Forbidden due to rate limit
        rate_limit_reset = int(response.headers.get(
            'X-RateLimit-Reset', time.time() + 3600))
        # Sleep until the reset time or 1 hour
        sleep_time = max(rate_limit_reset - int(time.time()), 3600)
        logging.info(
            f"Rate limit exceeded in has_organization(). Sleeping for {sleep_time} seconds...")
        time.sleep(sleep_time)
        return has_organization(URL)  # Retry after sleeping
    data = response.json()
    # print(data)
    # print(response.headers['X-RateLimit-Limit'])
    # print(response.headers['X-RateLimit-Remaining'])
    # print(response.headers['X-RateLimit-Reset'])
    if data:  # Check if the content is non-empty
        return True
    return False


logging.basicConfig(
    format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
)
df = pd.read_csv('data/241001/fake_user_info.csv')

logging.info("number of actors: ", df.shape[0])
existing_actors = df[df['error'].isna()]
logging.info("number of existing actors: ", existing_actors.shape[0])
# Iterate through each row
default_avatar = 0
no_organization = 0
no_blog = 0
no_company = 0
for index, row in existing_actors.iterrows():
    actor = row['actor']
    logging.info(f"Scanning actor {actor}...")
    raw_response = row['raw_response']
    try:
        # Parse the raw_response as JSON
        response_data = json.loads(raw_response)

        # Extract organizations_url and avatar_url
        organizations_url = response_data.get('organizations_url', 'Not Found')
        avatar_url = response_data.get('avatar_url', 'Not Found')
        blog_url = response_data.get('blog', 'Not Found')
        company = response_data.get('company', 'Not Found')

        # Print or process the URLs
        # print(f"Actor: {actor}")
        # print(f"Organizations URL: {organizations_url}")
        # print(f"Avatar URL: {avatar_url}")
        # print(f"blog URL: {blog_url}")
        # print(f"company: {company}")
        # print("-" * 40)

        if is_image_default(avatar_url):
            default_avatar += 1
        if not has_organization(organizations_url):
            no_organization += 1
        if blog_url == '':
            no_blog += 1
        if company == None:
            no_company += 1
    except json.JSONDecodeError:
        logging.info(f"Error decoding JSON for actor: {actor}")
logging.info("Done!", default_avatar, no_organization, no_blog, no_company)
