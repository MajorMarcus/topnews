import random
from flask import Flask, jsonify, request
from bs4 import BeautifulSoup
import aiohttp
import asyncio
from unidecode import unidecode
import re
import urllib
from datetime import datetime, timezone
import httpx
from dateutil import parser

app = Flask(__name__)


from groq import Groq
proxies = {
    "http://": "https://groqcall.ai/proxy/groq/v1",
}

# Custom client to handle proxy
class ProxyHttpxClient(httpx.Client):
    def __init__(self, proxies=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if proxies:
            self.proxies = proxies


clients = [
    Groq(api_key=key, http_client=ProxyHttpxClient(proxies=proxies))
    for key in [
        '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',
        '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',
        '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',
        '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',
        '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'
    ]
]


WOMENS_WORDS = frozenset([
    'wsl', "women", "women's", "womens", "female", "ladies", "girls", "nwsl", 
    "fa wsl", "female football", "mujer", "damas", "femme", "calcio femminile", 
    "football féminin", "fußball frauen", "she", "her", "w-league"
])


# Compile regex pattern for efficiency
PATTERN = re.compile(r"\(Photo by [^)]+\)")
IMAGE_KEY = "image="

async def batch_rephrase_titles(titles, batch_size=10):
    if not titles:
        return []
    
    titles_prompt = "\n".join([f"{i+1}. {title}" for i, title in enumerate(titles)])
    prompt = f"Rephrase these football news article titles to 6-9 words each without changing meaning:\n{titles_prompt}"
    
    results = []
    for i in range(0, len(titles), batch_size):
        batch = titles[i:i + batch_size]
        client = clients[i % len(clients)]
        
        try:
            completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama3-8b-8192",
                temperature=0,
                top_p=0,
            )
            batch_results = [
                content.split(". ", 1)[-1]
                for content in completion.choices[0].message.content.split("\n")
                if ". " in content
            ]
            results.extend(batch_results)
        except Exception as e:
            print(f"Error in title rephrasing: {e}")
            results.extend(batch)  # Fallback to original titles
            
    return results


async def batch_rephrase_content(contents):
    if not contents:
        return []

    batch_size = 2
    results = []
    
    async def process_batch(client, batch):
        if not batch:
            return []
        prompt = (
            "Rephrase these football news articles into detailed summaries. Make them concise while keeping all details. "
            "only respond with the article content and dont give any intro for seamlessness to not break the 4th wall"
            "Avoid repetitive words and make it direct while maintaining the original meaning. Keep all names and keywords unchanged:\n" +

            "\n".join(f"{i+1}. {content}" for i, content in enumerate(batch))
        )
        try:
            completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama3-8b-8192",
                temperature=0,
                top_p=0,
            )
            return [
                content for content in completion.choices[0].message.content.split("\n")
                if content and not any(word in content.lower() for word in ['article:', 'summary:','article','Article','summaries', '*'])
            ]
        except Exception as e:
            print(f"Error in content rephrasing: {e}")
            return batch

    for i in range(0, len(contents), batch_size * len(clients)):
        tasks = []
        for j, client in enumerate(clients):
            start_idx = i + j * batch_size
            batch = contents[start_idx:start_idx + batch_size]
            if batch:
                tasks.append(process_batch(client, batch))
        
        batch_results = await asyncio.gather(*tasks)
        for batch_result in batch_results:
            if 'article' in batch_result:
                print(batch_result)
                continue
            else:
                results.extend(batch_result)
    
    return results

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

def contains_word_from_list(text):
    words_in_text = set(PATTERN.findall(text.lower()))
    return bool(words_in_text & WOMENS_WORDS)

async def fetch_article(session, link, source, womens):
    print(link)
    async with session.get(link) as response:
        html = await response.text()
        soup = BeautifulSoup(html, 'html.parser')
        text_elements, attribution = extract_text_with_spacing(str(soup))
        
        if not text_elements or (womens is False and (contains_word_from_list(text_elements))):
            return None
        elif source == '90min':
            paras = soup.find_all('p', class_='tagStyle_z4kqwb-o_O-style_1tcxgp3-o_O-style_1pinbx1-o_O-style_48hmcm')
            paras_text = ' '.join(p.text for p in paras)
            img = soup.find('img', class_='base_1emrqjj')['src'] if soup.find('img', class_='base_1emrqjj') else ''
            img = img.replace('w_720,', '')
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
        

            
async def fetch_articles(page, womens):
    async with aiohttp.ClientSession(trust_env=True) as session:
        # Fetch 90min articles
        async with session.get(f'https://www.90min.com/categories/football-news?page={page}') as response:
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            links_90min = [a.find('a')['href'] for a in soup.find_all('article', class_='style_1wqwdi9-o_O-wrapper_1wgo221') if 'prediction' not in a.find('a')['href']]

        # Fetch OneFootball articles

        # Fetch content concurrently
        tasks = [fetch_article(session, link, '90min', womens=womens) for link in links_90min[:15]]
        articles = await asyncio.gather(*tasks)

        # Filter out None values and limit to 10 article
        articles = [article for article in articles if article is not None]

        # Rephrase titles and contents
        rephrased_titles = await batch_rephrase_titles([article['title'] for article in articles])
        rephrased_contents = await batch_rephrase_content([article['article_content'] for article in articles])

        # Ensure articles are unique by their titles
        unique_articles = {}
        for article in articles:
            if article['title'] not in unique_articles:
                unique_articles[article['title']] = article

        # Convert the dictionary back to a list
        articles = list(unique_articles.values())

        for i, article in enumerate(articles):
            article['title'] = rephrased_titles[i]
            article['article_content'] = rephrased_contents[i]

        return articles
@app.route('/topnews', methods=['GET'])
async def get_top_news():
    page = request.args.get('page', default=1, type=int)
    womens = request.args.get('womens', default=False, type=bool)
    articles = await fetch_articles(page, womens=womens)
    # Ensure only 10 articles are returned
    return jsonify({'news_items': articles})


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False) 
