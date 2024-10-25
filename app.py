import random
from flask import Flask, jsonify, request
from bs4 import BeautifulSoup
import aiohttp
import asyncio
from unidecode import unidecode
import re
import urllib
from datetime import datetime, timezone
from dateutil import parser

app = Flask(__name__)

# Compile regex pattern for efficiency
PATTERN = re.compile(r"\(Photo by [^)]+\)")
IMAGE_KEY = "image="

def extract_text_with_spacing(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    textelements = []
    attribution = None
    for p in soup.find_all('p'):
        text = p.get_text()
        text_without_attribution = PATTERN.sub('', text).strip()
        textelements.append(text_without_attribution)
        
        match = PATTERN.search(text)
        if match:
            attribution = match.group()
    
    return [' '.join(textelements), attribution]

def extract_actual_url(url):
    start = url.find(IMAGE_KEY)

    if start == -1 or any(sub in url for sub in ['betting', 'squawka', 'bit.ly', 'footballtoday.com']):
        return None
    return urllib.parse.unquote(url[start + len(IMAGE_KEY):]).replace('width=720', '')

def time_ago(iso_timestamp):
    event_time = parser.isoparse(iso_timestamp)
    current_time = datetime.now(timezone.utc)
    time_difference = current_time - event_time
    seconds = time_difference.total_seconds()

    minute, hour, day, week, month, year = 60, 3600, 86400, 604800, 2592000, 31536000

    if seconds < minute:
        return f"{int(seconds)} seconds ago"
    elif seconds < hour:
        return f"{int(seconds // minute)} minutes ago"
    elif seconds < day:
        return f"{int(seconds // hour)} hours ago"
    elif seconds < week:
        return f"{int(seconds // day)} days ago"
    elif seconds < month:
        return f"{int(seconds // week)} weeks ago"
    elif seconds < year:
        return f"{int(seconds // month)} months ago"
    else:
        return f"{int(seconds // year)} years ago"

async def fetch_article(session, link, source):
    print(link)
    async with session.get(link) as response:
        html = await response.text()
        soup = BeautifulSoup(html, 'html.parser')
        
        if source == '90min':
            paras = soup.find_all('p', class_='tagStyle_z4kqwb-o_O-style_1tcxgp3-o_O-style_1pinbx1-o_O-style_48hmcm')
            paras_text = ' '.join(p.text for p in paras)
            img = soup.find('img', class_='base_1emrqjj')['src'] if soup.find('img', class_='base_1emrqjj') else ''
            time = time_ago(soup.find('time')['datetime'])
            title = soup.find('h1', class_='tagStyle_mxz06e-o_O-title_dhip6x-o_O-sidesPadding_1kaga1a').text if soup.find('h1', class_='tagStyle_mxz06e-o_O-title_dhip6x-o_O-sidesPadding_1kaga1a') else ''
            return {

                'article_content': paras_text,
                'img_url': img,
                'time': time,
                'title': title,
                'publisher': '90min',
                'article_url': link,
                'article_id': random.randint(100000, 999999),
                'attribution':''
            }

        elif source == 'OneFootball':
            article_id = link[-8:]  # Extract the last 8 characters as article_id
            img_element = soup.find('img', class_='ImageWithSets_of-image__img__pezo7 ImageWrapper_media-container__image__Rd2_F')
            img_url = img_element['src'] if img_element else ''
            img_url = extract_actual_url(img_url)
            if img_url:
                title = soup.find('span', class_="ArticleHeroBanner_articleTitleTextBackground__yGcZl").text.strip() if soup.find('span', class_="ArticleHeroBanner_articleTitleTextBackground__yGcZl") else ''
                time = soup.find('p', class_='title-8-regular ArticleHeroBanner_providerDetails__D_5AV').find_all('span')[1].text.strip() if soup.find('p', class_='title-8-regular ArticleHeroBanner_providerDetails__D_5AV') else ''
                publisher = soup.find('p', class_='title-8-bold').text.strip() if soup.find('p', class_='title-8-bold') else ''
                textlist = extract_text_with_spacing(str(soup.find_all('div', class_='ArticleParagraph_articleParagraph__MrxYL')))
                text_elements = textlist[0]
                attribution = textlist[1]

                return {
                    'title': title,
                    'article_content': unidecode(text_elements),
                    'img_url': img_url,
                    'article_url': link,
                    'article_id': article_id,
                    'time': time,
                    'publisher': publisher,
                    'attribution': ''
                }
            else:
                return None
async def fetch_articles(page):
    async with aiohttp.ClientSession(trust_env=True) as session:
        # Fetch 90min articles
        async with session.get(f'https://www.90min.com/categories/football-news?page={page}') as response:
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            links_90min = [a.find('a')['href'] for a in soup.find_all('article', class_='style_1wqwdi9-o_O-wrapper_1wgo221') if 'prediction' not in a.find('a')['href']]

        # Fetch OneFootball articles
        async with session.get('https://www.onefootball.com/en/home') as response:
            html = await response.text()
            links_onefootball = [a['href'] for a in BeautifulSoup(html, 'html.parser').find_all('a') if '/news/' in a['href']]

        # Fetch content concurrently
        tasks = [fetch_article(session, link, '90min') for link in links_90min] + \
                [fetch_article(session, f'https://onefootball.com/{link}', 'OneFootball') for link in links_onefootball]
        articles = await asyncio.gather(*tasks)

        # Filter out None values
        articles = [article for article in articles if article is not None]

        # Make sure articles are unique by their titles
        unique_articles = {}
        for article in articles:
            if article['title'] not in unique_articles:
                unique_articles[article['title']] = article

        # Convert the dictionary back to a list and shuffle the articles
        articles = list(unique_articles.values())
      
        random.shuffle(articles)
        return articles

@app.route('/topnews', methods=['GET'])
async def get_top_news():
    page = request.args.get('page')
    articles = await fetch_articles(page)
    return jsonify({'news_items': articles})

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
