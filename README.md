
重點：

1. 程式碼，加入相關加快 feedly xml 讀取更新功能，例如

response = requests.post(
"https://pubsubhubbub.appspot.com/",
data={"hub.mode": "publish", "hub.url": feed_url},
)
<atom:link href="https://pubsubhubbub.appspot.com/" rel="hub" />

2. python 產生的 index.html  ,  rss.xml  在根目錄
