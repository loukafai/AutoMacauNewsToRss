import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import datetime
import email.utils
import xml.sax.saxutils as saxutils
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import os

def fetch_single_article(i, link, headers):
    """單篇文章抓取邏輯"""
    try:
        r = requests.get(link, headers=headers, timeout=15)
        r.encoding = 'utf-8'
        raw_html = r.text

        title_match = re.search(r'<founder-title>(.*?)</founder-title>', raw_html, re.DOTALL)
        final_title = title_match.group(1).strip() if title_match else "無標題"
        final_title = final_title.replace('<![CDATA[', '').replace(']]>', '')

        a_soup = BeautifulSoup(raw_html, 'html.parser')
        
        imgs_html = ""
        for img in a_soup.find_all('img'):
            src = img.get('src')
            if src and '/res/' in src:
                full_img_url = urljoin(link, src)
                imgs_html += f'<figure><img src="{full_img_url}" style="max-width:100%;height:auto;"></figure><br>'

        content_div = a_soup.find(id="ozoom")
        content_html = str(content_div) if content_div else "<p>（內文擷取失敗）</p>"
        full_content = f"{imgs_html}{content_html}".replace(']]>', ']]&gt;')

        return (i, final_title, link, full_content)
    except Exception as e:
        print(f"❌ 抓取失敗: {link} - {str(e)}")
        return (i, "抓取失敗", link, f"<p>錯誤: {str(e)}</p>")

def start_multi_threaded_crawler(target_url, num_threads=8):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0"
    }

    print(f"🔍 開始解析目錄: {target_url}")
    try:
        res = requests.get(target_url, headers=headers, timeout=15)
        if res.status_code != 200:
            print(f"⚠️ 無法取得網頁 (HTTP {res.status_code})，可能今日報紙尚未更新。")
            return None

        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        links = []
        for a in soup.find_all('a', href=True):
            if 'content_' in a['href']:
                links.append(urljoin(target_url, a['href']))
        
        article_links = list(dict.fromkeys(links))
        total = len(article_links)
        
        if total == 0:
            print("⚠️ 找不到任何文章連結。")
            return None

        print(f"🚀 找到 {total} 篇文章，啟動 {num_threads} 線程處理中...")
        results = []
        
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            future_to_url = {executor.submit(fetch_single_article, i, link, headers): i for i, link in enumerate(article_links)}
            
            completed_count = 0
            for future in as_completed(future_to_url):
                results.append(future.result())
                completed_count += 1
                if completed_count % 10 == 0 or completed_count == total:
                    print(f"⏳ 進度: {completed_count}/{total}")

        # 按原始順序排序
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

        # 組合 XML
        xml_parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
            '  <channel>',
            f'    <title>澳門日報 - {date_str}</title>',
            f'    <link>{target_url}</link>',
            '    <description>澳門日報當日新聞自動抓取訂閱源 (GitHub Actions 自動生成)</description>',
            '    <language>zh-hk</language>',
            f'    <pubDate>{rfc_date}</pubDate>',
            f'    <lastBuildDate>{last_build_date}</lastBuildDate>'
        ]

        for r in results:
            idx, title, link, content = r
            safe_title = saxutils.escape(title)
            safe_link = saxutils.escape(link)
            
            xml_parts.append('    <item>')
            xml_parts.append(f'      <title>{safe_title}</title>')
            xml_parts.append(f'      <link>{safe_link}</link>')
            xml_parts.append(f'      <guid isPermaLink="true">{safe_link}</guid>')
            xml_parts.append(f'      <pubDate>{rfc_date}</pubDate>')
            xml_parts.append(f'      <description><![CDATA[{content}]]></description>')
            xml_parts.append('    </item>')

        xml_parts.append('  </channel>')
        xml_parts.append('</rss>')

        print("✨ RSS 轉換完成！")
        return "\n".join(xml_parts)

    except Exception as e:
        print(f"❌ 發生嚴重錯誤: {e}")
        return None

if __name__ == "__main__":
    # 確保取得的是 UTC+8 (澳門時間) 的今天日期
    tz = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(tz)
    formatted_date = now.strftime("%Y-%m/%d")
    
    today_url = f"https://www.macaodaily.com/html/{formatted_date}/node_1.htm"
    
    xml_content = start_multi_threaded_crawler(today_url, num_threads=8)
    
    if xml_content:
        # 將結果寫入 rss.xml
        with open("rss.xml", "w", encoding="utf-8") as f:
            f.write(xml_content)
        print("✅ 成功生成 rss.xml")
    else:
        print("⚠️ 抓取中斷，未生成新的 rss.xml。可能今日報紙尚未出刊。")
        sys.exit(0) # 以正常狀態退出，避免 Github Action 報錯紅燈
