from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import os
import re
import time
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

# 設定澳門時區 (UTC+8)
MACAU_TZ = timezone(timedelta(hours=8))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def get_soup(url):
  """發送請求並回傳 BeautifulSoup 物件"""
  try:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = "utf-8"
    if resp.status_code == 200:
      return BeautifulSoup(resp.text, "html.parser")
  except Exception as e:
    print(f"❌ 請求錯誤 {url}: {e}")
  return None


def get_all_article_urls(base_column_url, year_month, day):
  """從版面頁自動掃描並萃取出當日所有新聞內文連結"""
  article_urls = []
  visited_columns = set()
  columns_to_visit = [base_column_url]

  content_pattern = re.compile(rf"/content/{year_month}/{day}/c\d+\.html")
  column_pattern = re.compile(rf"/column/{year_month}/{day}/col[A-Z0-9]+\.html")

  while columns_to_visit:
    col_url = columns_to_visit.pop(0)
    if col_url in visited_columns:
      continue
    visited_columns.add(col_url)

    print(f"🔍 正在掃描版面: {col_url}")
    soup = get_soup(col_url)
    if not soup:
      continue

    for a_tag in soup.find_all("a", href=True):
      full_url = urljoin(col_url, a_tag["href"]).split("#")[0]

      if content_pattern.search(full_url) and full_url not in article_urls:
        article_urls.append(full_url)
      elif (
          column_pattern.search(full_url)
          and full_url not in visited_columns
          and full_url not in columns_to_visit
      ):
        columns_to_visit.append(full_url)

  return article_urls


def parse_article(index, url):
  """解析單篇新聞內文頁的標題、內文與圖片（包含各項防重覆與過濾小圖規則）"""
  print(f"📄 [{index}] 正在解析: {url}")
  soup = get_soup(url)
  if not soup:
    return index, None

  # 1. 移除干擾元素
  for tag in soup(["script", "style", "iframe", "nav", "header", "footer"]):
    tag.decompose()

  # 2. 移除重複出現的版面預覽圖區塊
  for tag in soup.find_all(
      class_=re.compile(r"preview|paper-img-layout", re.I)
  ):
    tag.decompose()

  title_tag = (
      soup.find("h1")
      or soup.find("h2")
      or soup.find(class_=re.compile(r"title|headline", re.I))
  )
  title = title_tag.get_text(strip=True) if title_tag else "無標題新聞"

  content_div = soup.find(
      "div",
      class_=re.compile(r"content|article|text|detail|founder", re.I),
  )

  paragraphs = []
  images = []

  target_area = content_div if content_div else soup.body
  if target_area:
    for p in target_area.find_all("p"):
      text = p.get_text(strip=True)
      if len(text) > 1:
        paragraphs.append(text)

    # 3. 篩選新聞內文圖片
    for img in target_area.find_all("img", src=True):
      img_src = urljoin(url, img["src"])

      img_classes = img.get("class", [])
      if isinstance(img_classes, list):
        img_classes_str = " ".join(img_classes).lower()
      else:
        img_classes_str = str(img_classes).lower()

      # 規則 1：過濾 paper-img-origin 且網址帶有 _s 的小縮圖
      if "paper-img-origin" in img_classes_str and "_s" in img_src:
        continue

      # 規則 2：過濾預設頭像/小圖 woman.png
      if "woman.png" in img_src.lower():
        continue

      # 規則 3：過濾其他通用 icon、logo、btn 等
      if any(
          kw in img_src.lower()
          for kw in ["icon", "logo", "btn", "qr", "banner"]
      ):
        continue

      images.append(img_src)

  if not paragraphs:
    return index, None

  return index, {
      "url": url,
      "title": title,
      "paragraphs": paragraphs,
      "images": images,
  }


def build_html(articles, date_str):
  """將所有新聞彙整成帶有目錄與 RSS 訂閱連結的精美閱讀網頁"""
  toc_items = []
  article_blocks = []

  for idx, art in enumerate(articles, 1):
    art_id = f"art-{idx}"
    toc_items.append(f'<li><a href="#{art_id}">{idx}. {art["title"]}</a></li>')

    imgs_html = "".join(
        f'<img src="{src}" alt="新聞圖片" loading="lazy">'
        for src in art["images"]
    )
    paras_html = "".join(f"<p>{p}</p>" for p in art["paragraphs"])

    article_blocks.append(f"""
        <article id="{art_id}" class="news-card">
            <h2>{idx}. {art["title"]}</h2>
            <div class="meta">
                <a href="{art["url"]}" target="_blank" rel="noopener">查看原始頁面 ↗</a>
            </div>
            {imgs_html}
            <div class="news-text">
                {paras_html}
            </div>
            <div class="back-top"><a href="#top">↑ 回到頂部目錄</a></div>
        </article>
        """)

  return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>澳門日報每日精讀 - {date_str}</title>
    <link rel="alternate" type="application/rss+xml" title="澳門日報每日精讀 RSS" href="rss.xml" />
    <style>
        :root {{
            --bg-color: #f5f5f0;
            --card-bg: #ffffff;
            --text-color: #2b2b2b;
            --accent-color: #b71c1c;
            --border-color: #e0dfd5;
        }}
        html {{ scroll-behavior: smooth; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "PingFang TC", "Microsoft JhengHei", sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            line-height: 1.85;
            margin: 0;
            padding: 15px;
        }}
        .container {{ max-width: 820px; margin: 0 auto; }}
        header {{
            background: var(--card-bg); padding: 30px; border-radius: 12px;
            text-align: center; box-shadow: 0 2px 12px rgba(0,0,0,0.05);
            margin-bottom: 24px; border-top: 5px solid var(--accent-color);
        }}
        header h1 {{ margin: 0 0 8px 0; color: var(--accent-color); font-size: 1.8rem; }}
        .subtitle {{ color: #666; font-size: 0.95rem; margin-bottom: 15px; }}
        .rss-btn {{
            display: inline-block; background: #e67e22; color: white; padding: 6px 14px;
            border-radius: 20px; text-decoration: none; font-size: 0.85rem; font-weight: bold;
        }}
        .rss-btn:hover {{ background: #d35400; }}
        .toc {{
            background: var(--card-bg); padding: 25px 30px; border-radius: 12px;
            margin-bottom: 30px; box-shadow: 0 2px 12px rgba(0,0,0,0.05);
        }}
        .toc h3 {{ margin-top: 0; border-bottom: 1px solid var(--border-color); padding-bottom: 10px; color: #444; }}
        .toc ul {{ list-style: none; padding: 0; margin: 0; }}
        .toc li {{ margin-bottom: 10px; border-bottom: 1px dashed #eee; padding-bottom: 6px; }}
        .toc a {{ text-decoration: none; color: #1a5276; font-weight: 500; }}
        .toc a:hover {{ color: var(--accent-color); text-decoration: underline; }}
        .news-card {{
            background: var(--card-bg); padding: 35px 40px; border-radius: 12px;
            margin-bottom: 28px; box-shadow: 0 2px 12px rgba(0,0,0,0.05);
        }}
        .news-card h2 {{ margin-top: 0; color: #111; font-size: 1.45rem; line-height: 1.4; }}
        .meta {{ font-size: 0.85rem; margin-bottom: 20px; }}
        .meta a {{ color: #888; text-decoration: none; }}
        .news-text p {{ text-indent: 2em; margin-bottom: 1.1em; font-size: 1.1rem; text-align: justify; }}
        .news-card img {{ max-width: 100%; height: auto; display: block; margin: 20px auto; border-radius: 8px; }}
        .back-top {{ text-align: right; margin-top: 20px; font-size: 0.85rem; }}
        .back-top a {{ color: #888; text-decoration: none; }}
        footer {{ text-align: center; color: #888; font-size: 0.85rem; padding: 20px 0 40px; }}
        @media (max-width: 600px) {{
            .news-card {{ padding: 22px 20px; }}
            .toc {{ padding: 20px; }}
            header h1 {{ font-size: 1.5rem; }}
        }}
    </style>
</head>
<body id="top">
    <div class="container">
        <header>
            <h1>澳門日報每日精讀</h1>
            <div class="subtitle">{date_str} ｜ 共收錄 {len(articles)} 篇報導</div>
            <a href="rss.xml" target="_blank" class="rss-btn">📡 訂閱 RSS 頻訊</a>
        </header>

        <nav class="toc">
            <h3>📑 當日新聞目錄</h3>
            <ul>{''.join(toc_items)}</ul>
        </nav>
        <main>{''.join(article_blocks)}</main>
        <footer>自動彙整於 {datetime.now(MACAU_TZ).strftime('%Y-%m-%d %H:%M:%S')} (澳門時間)</footer>
    </div>
</body>
</html>
"""


def build_rss(articles, date_str):
  """生成標準的 RSS 2.0 XML 內容"""
  now_rfc822 = datetime.now(MACAU_TZ).strftime("%a, %d %b %Y %H:%M:%S +0800")
  rss_items = []

  for art in articles:
    imgs_html = "".join(
        f'<img src="{src}" style="max-width:100%; height:auto;" /><br>'
        for src in art["images"]
    )
    paras_html = "".join(f"<p>{p}</p>" for p in art["paragraphs"])
    full_content = f"{imgs_html}{paras_html}"

    rss_items.append(f"""    <item>
        <title><![CDATA[{art['title']}]]></title>
        <link>{art['url']}</link>
        <guid>{art['url']}</guid>
        <pubDate>{now_rfc822}</pubDate>
        <description><![CDATA[{full_content}]]></description>
    </item>""")

  rss_xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
<channel>
    <title><![CDATA[澳門日報每日精讀 - {date_str}]]></title>
    <link>https://github.com</link>
    <description><![CDATA[自動抓取、清理廣告並重新排版的澳門日報精選內容]]></description>
    <language>zh-Hant</language>
    <lastBuildDate>{now_rfc822}</lastBuildDate>
    {''.join(rss_items)}
</channel>
</rss>"""
  return rss_xml


def main():
  now = datetime.now(MACAU_TZ)
  year_month = now.strftime("%Y%m")
  day = now.strftime("%d")
  date_str = now.strftime("%Y年%m月%d日")

  start_url = (
      f"https://nginx-amrb.modaily.cn/amrb/epaper/column/{year_month}/{day}/colA01.html"
  )
  print(f"🚀 開始執行 {date_str} 澳門日報多線程抓取任務：{start_url}")

  article_urls = get_all_article_urls(start_url, year_month, day)
  print(f"✅ 共找到 {len(article_urls)} 篇新聞連結")

  if not article_urls:
    print("⚠️ 今日尚未出報或找不到新聞連結，結束執行。")
    return

  results = []
  max_workers = 10

  print(f"⚡ 啟動多線程爬蟲，並行抓取中...")
  with ThreadPoolExecutor(max_workers=max_workers) as executor:
    future_to_url = {
        executor.submit(parse_article, idx, url): url
        for idx, url in enumerate(article_urls, 1)
    }

    for future in as_completed(future_to_url):
      try:
        idx, art_data = future.result()
        if art_data:
          results.append((idx, art_data))
      except Exception as e:
        print(f"❌ 執行緒發生例外錯誤: {e}")

  results.sort(key=lambda x: x[0])
  articles = [item[1] for item in results]

  if articles:
    # 直接輸出至專案根目錄
    html_output_path = "index.html"
    with open(html_output_path, "w", encoding="utf-8") as f:
      f.write(build_html(articles, date_str))
    print(f"🎉 成功生成網頁（根目錄）：{html_output_path}")

    rss_output_path = "rss.xml"
    with open(rss_output_path, "w", encoding="utf-8") as f:
      f.write(build_rss(articles, date_str))
    print(f"📡 成功生成 RSS 訂閱檔（根目錄）：{rss_output_path}")

  else:
    print("❌ 未能成功解析任何新聞內文。")


if __name__ == "__main__":
  main()
