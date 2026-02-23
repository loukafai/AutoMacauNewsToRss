import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import datetime
import email.utils
import xml.sax.saxutils as saxutils
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

def clean_xml_text(text):
    """移除可能導致 XML 崩潰的隱藏控制字元"""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)

def ping_websub(feed_url):
    """主動通知 WebSub Hub 進行即時推播"""
    hub_url = "https://pubsubhubbub.appspot.com/"
    print(f"📡 準備發送 WebSub Ping 通知 Hub: {hub_url}")
    data = {
        "hub.mode": "publish",
        "hub.url": feed_url
    }
    try:
        response = requests.post(hub_url, data=data, timeout=10)
        # WebSub 成功通常回傳 204 No Content 或 200 OK
        if response.status_code in [200, 204]:
            print("✅ 成功 Ping WebSub Hub！Feedly 稍後將收到即時更新通知。")
        else:
            print(f"⚠️ Ping WebSub Hub 失敗，HTTP 狀態碼: {response.status_code}")
    except Exception as e:
        print(f"⚠️ Ping WebSub Hub 發生錯誤: {e}")

def fetch_single_article(i, link, headers):
    try:
        r = requests.get(link, headers=headers, timeout=15)
        r.encoding = 'utf-8'
        raw_html = r.text

        title_match = re.search(r'<founder-title>(.*?)</founder-title>', raw_html, re.DOTALL)
        final_title = title_match.group(1).strip() if title_match else "無標題"
        final_title = clean_xml_text(final_title.replace('<![CDATA[', '').replace(']]>', ''))

        a_soup = BeautifulSoup(raw_html, 'html.parser')
        
        imgs_html = ""
        for img in a_soup.find_all('img'):
            src = img.get('src')
            if src and '/res/' in src:
                full_img_url = urljoin(link, src)
                imgs_html += f'<figure style="margin-bottom: 20px;"><img src="{full_img_url}" style="max-width:100%; height:auto;" /></figure>'

        content_div = a_soup.find(id="ozoom")
        if content_div:
            for tag in content_div(["script", "style"]):
                tag.decompose()
            for br in content_div.find_all("br"):
                br.replace_with("\n")
                
            raw_text = content_div.get_text(separator='\n', strip=True)
            raw_text = clean_xml_text(raw_text)
            
            clean_paragraphs = []
            for line in raw_text.split('\n'):
                line = line.strip()
                if line:
                    clean_paragraphs.append(f"<p>{line}</p>")
            
            content_html = "".join(clean_paragraphs)
            summary_text = raw_text.replace('\n', ' ')
            summary = summary_text[:150] + "..." if len(summary_text) > 150 else summary_text
        else:
            summary = "無內容"
            content_html = "<p>（內文擷取失敗）</p>"

        full_content = f"{imgs_html}{content_html}".replace(']]>', ']]&gt;')
        summary = summary.replace('<![CDATA[', '').replace(']]>', '')

        return (i, final_title, link, full_content, summary)
    except Exception as e:
        print(f"❌ 抓取失敗: {link} - {str(e)}")
        return (i, "抓取失敗", link, f"<p>錯誤: {str(e)}</p>", "抓取失敗")

def start_multi_threaded_crawler(target_url, feed_url, num_threads=8):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0"
    }

    print(f"🔍 嘗試取得版面: {target_url}")
    try:
        res = requests.get(target_url, headers=headers, timeout=15)
        if res.status_code != 200:
            return None

        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        links = []
        for a in soup.find_all('a', href=True):
            if 'content_' in a['href']:
                links.append(urljoin(target_url, a['href']))
        
        article_links = list(dict.fromkeys(links))
        total = len(article_links)
        
        if total == 0: return None

        print(f"🚀 找到 {total} 篇文章，啟動 {num_threads} 線程處理中...")
        results = []
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            future_to_url = {executor.submit(fetch_single_article, i, link, headers): i for i, link in enumerate(article_links)}
            for future in as_completed(future_to_url):
                results.append(future.result())

        results.sort(key=lambda x: x[0])

        date_match = re.search(r'(\d{4}-\d{2}/\d{2})', target_url)
        date_str = date_match.group(1) if date_match else "Archive"
        
        if date_match:
            dt = datetime.datetime.strptime(date_str, "%Y-%m/%d")
            tz = datetime.timezone(datetime.timedelta(hours=8))
            pub_dt = dt.replace(tzinfo=tz, hour=8, minute=0)
        else:
            pub_dt = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        
        rfc_date = email.utils.format_datetime(pub_dt)
        last_build_date = email.utils.format_datetime(datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))))

        # 加入 xmlns:atom 命名空間與 WebSub 核心宣告
        xml_parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">',
            '  <channel>',
            f'    <title>澳門日報</title>',
            f'    <link>https://www.macaodaily.com</link>',
            '    <description>澳門日報當日新聞自動抓取訂閱源</description>',
            '    <language>zh-hk</language>',
            f'    <pubDate>{rfc_date}</pubDate>',
            f'    <lastBuildDate>{last_build_date}</lastBuildDate>',
            f'    <atom:link href="{feed_url}" rel="self" type="application/rss+xml" />',
            '    <atom:link href="https://pubsubhubbub.appspot.com/" rel="hub" />'
        ]

        for r in results:
            idx, title, link, content, summary = r
            
            safe_title = saxutils.escape(title)
            safe_link = saxutils.escape(link)
            
            xml_parts.append('    <item>')
            xml_parts.append(f'      <title>{safe_title}</title>')
            xml_parts.append(f'      <link>{safe_link}</link>')
            xml_parts.append(f'      <guid isPermaLink="true">{safe_link}</guid>')
            xml_parts.append(f'      <pubDate>{rfc_date}</pubDate>')
            xml_parts.append(f'      <description><![CDATA[{summary}]]></description>')
            xml_parts.append(f'      <content:encoded><![CDATA[{content}]]></content:encoded>')
            xml_parts.append('    </item>')

        xml_parts.append('  </channel>')
        xml_parts.append('</rss>')

        return "\n".join(xml_parts)

    except Exception as e:
        print(f"❌ 發生嚴重錯誤: {e}")
        return None

if __name__ == "__main__":
    # 您的真實 GitHub Raw 網址
    GITHUB_RAW_URL = "https://raw.githubusercontent.com/loukafai/AutoMacauNewsToRss/refs/heads/main/rss.xml"

    tz = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(tz)
    
    formatted_date = now.strftime("%Y-%m/%d")
    today_url = f"https://www.macaodaily.com/html/{formatted_date}/node_1.htm"
    
    xml_content = start_multi_threaded_crawler(today_url, GITHUB_RAW_URL, num_threads=8)
    
    if not xml_content:
        print("🔄 今天報紙尚未更新，自動退回嘗試抓取昨天的報紙...")
        yesterday = now - datetime.timedelta(days=1)
        formatted_date_yesterday = yesterday.strftime("%Y-%m/%d")
        yesterday_url = f"https://www.macaodaily.com/html/{formatted_date_yesterday}/node_1.htm"
        xml_content = start_multi_threaded_crawler(yesterday_url, GITHUB_RAW_URL, num_threads=8)
    
    if xml_content:
        with open("rss.xml", "w", encoding="utf-8") as f:
            f.write(xml_content)
        print("✅ 成功生成 rss.xml！")
        
        # 發送 Ping 給 WebSub 伺服器，告知 Feedly 立刻來抓更新
        ping_websub(GITHUB_RAW_URL)
