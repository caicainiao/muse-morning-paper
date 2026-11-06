# -*- coding: utf-8 -*-
import os
import sys
import re
import urllib.parse
import zipfile
import requests
from datetime import datetime, timezone, timedelta

# 获取北京时间 (UTC+8)
tz_cst = timezone(timedelta(hours=8))
now = datetime.now(tz_cst)
date_str = now.strftime("%Y-%m-%d")
weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
weekday_str = weekdays[now.weekday()]

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("错误：未找到 GEMINI_API_KEY 环境变量！")
    sys.exit(1)

# 第一步：直接向 Google 查询当前账号允许使用的所有模型
print("正在自动查询 Google AI Studio 允许调用的模型列表...")
list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
list_resp = requests.get(list_url, timeout=30)

if list_resp.status_code != 200:
    print(f"【API Key 验证失败】({list_resp.status_code}): {list_resp.text}")
    sys.exit(1)

available_models = []
for m in list_resp.json().get("models", []):
    methods = m.get("supportedGenerationMethods", [])
    if "generateContent" in methods:
        available_models.append(m.get("name"))

print(f"【成功获取可用模型】共 {len(available_models)} 个模型:")
for m in available_models[:8]:
    print("  -", m)

# 优选包含 flash 的最新模型
target_model = None
for pref in ["models/gemini-3.8-flash", "models/gemini-2.0-flash", "models/gemini-flash-latest"]:
    if pref in available_models:
        target_model = pref
        break

if not target_model and available_models:
    target_model = available_models[0]

print(f"\n>>> 自动锁定目标模型: 【{target_model}】 <<<")

def call_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.2
        }
    }
    headers = {"Content-Type": "application/json"}
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    
    # 如果带 search tool 失败，降级尝试无 search 纯模型，并打印原因
    if resp.status_code != 200:
        print(f"带联网搜索调用失败 ({resp.status_code}): {resp.text}")
        print("尝试降级调用 (不带 tools)...")
        payload.pop("tools", None)
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code != 200:
            raise Exception(f"模型调用失败 ({resp.status_code}): {resp.text}")

    data = resp.json()
    parts = data["candidates"][0]["content"]["parts"]
    return "".join([p.get("text", "") for p in parts])

def clean_xml_and_urls(text):
    def unwrap_meta(match):
        full_url = match.group(1)
        if "l.meta.ai/?u=" in full_url:
            parsed = urllib.parse.urlparse(full_url)
            qs = urllib.parse.parse_qs(parsed.query)
            if 'u' in qs:
                return f'href="{qs["u"][0]}"'
        return f'href="{full_url}"'

    text = re.sub(r'href="([^"]+)"', unwrap_meta, text)
    text = re.sub(r'&(?!(amp|lt|gt|quot|apos);)', '&amp;', text)
    return text

def format_to_html(raw_text):
    raw_text = re.sub(r'^```(html|markdown)?\s*', '', raw_text.strip(), flags=re.MULTILINE)
    raw_text = re.sub(r'```$', '', raw_text.strip(), flags=re.MULTILINE)

    lines = raw_text.split('\n')
    html_lines = []
    in_card = False

    for line in lines:
        l = line.strip()
        if not l:
            continue

        if l.startswith('# '):
            html_lines.append(f'<h2>{l[2:]}</h2>')
            continue
        elif l.startswith('## '):
            html_lines.append(f'<h3>{l[3:]}</h3>')
            continue
        elif l.startswith('### '):
            html_lines.append(f'<h4>{l[4:]}</h4>')
            continue

        if "晨报 ·" in l and ("<h2>" not in l):
            html_lines.append(f'<h2>{l}</h2>')
            continue

        if l.startswith("今日一句话：") or l.startswith("来源："):
            html_lines.append(f'<div class="meta-box"><p>{l}</p></div>')
            continue

        if re.match(r'^[1-9]\.\s+', l):
            if in_card:
                html_lines.append('</div>')
                in_card = False
            html_lines.append(f'<div class="section-header">{l}</div>')
            continue

        if any(keyword in l for keyword in ["摘要：", "为什么值得看：", "点数：", "链接："]):
            l = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'<a href="\2">\1</a>', l)
            l = re.sub(r'\*\*([^\*]+)\*\*', r'<strong>\1</strong>', l)
            html_lines.append(f'<p class="item-field">{l}</p>')
            continue

        if any(h in l for h in ["模型官方博客速览", "开源与社区速览", "口径说明", "和你相关的"]):
            if in_card:
                html_lines.append('</div>')
                in_card = False
            html_lines.append(f'<div class="sub-header">{l}</div>')
            continue

        l = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'<a href="\2">\1</a>', l)
        l = re.sub(r'\*\*([^\*]+)\*\*', r'<strong>\1</strong>', l)
        html_lines.append(f'<p>{l}</p>')

    if in_card:
        html_lines.append('</div>')

    joined = "\n".join(html_lines)
    return clean_xml_and_urls(joined)

print("\n正在生成【智能建筑资讯晨报】...")
prompt_building = f"""
今天是 {date_str}（{weekday_str}）。请检索过去 24 小时内关于“智能建筑、IBMS、综合能源管理、楼宇自控、建筑 AI 节能”的最新动态，严格按以下格式输出：

智能建筑资讯晨报 · {date_str}（{weekday_str}）
来源：过去约 24 小时公开资讯，覆盖 IBMS、综合能源管理、相关 AI 与预防性维护策略/引擎。
今日一句话：（提炼今日最关键的行业核心洞察）

1. IBMS 智能建筑管理平台
（整理最新更新，若无重大更新注明未检索到）

2. 综合能源管理平台
（整理项目进展，含技术亮点、为什么值得看与链接）

3. 智能建筑相关 AI
（详细整理具体落地案例与研讨，包含为什么值得看与链接）

4. 预防性维护策略/引擎
（整理设备故障诊断动态，若无注明）

5. 其他值得看的
（建筑创新成果，包含为什么值得看与链接）

口径说明：（简要说明检索时间窗口及去重标准）
"""
raw_building = call_gemini(prompt_building)
content_building = format_to_html(raw_building)

print("正在生成【AI 晨报】...")
prompt_ai = f"""
今天是 {date_str}（{weekday_str}）。请检索过去 24 小时内权威科技动态，严格按以下结构输出《AI 晨报》：

AI 晨报 · {date_str}（{weekday_str}）
来源：Hacker News 首页及 HN 热议链接 + 各大模型官方博客 + 开源社区，权威科技媒体作交叉核验，覆盖过去约 24 小时。
今日一句话：（提炼今日行业暗线与核心大事件）

（输出 4~6 条 Hacker News 首页深度热点，每条格式如下）：
条目标题
摘要：（核心事实、技术原理）
为什么值得看：（深度洞察与行业启示）
点数：（点数 / 评论数快照）
链接：[链接文本](真实原文URL)

和你相关的 1 条：（精选 1 条关于 Claude Code、Agent 实战热点）
摘要：...
为什么值得看：...
点数：...
链接：...

模型官方博客速览
（整理 OpenAI、Anthropic、Google 等大厂官方博客动态）

开源与社区速览
（整理 2 个 GitHub Trending 上的顶级开源项目，标注定位、Star 数、开源协议及链接）

口径说明：（说明快照时间与去重准则）
"""
raw_ai = call_gemini(prompt_ai)
content_ai = format_to_html(raw_ai)

CSS_STYLE = """
@charset "utf-8";
body {
    margin: 4% 3%;
    padding: 0;
    font-family: "LXGW WenKai Screen", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    line-height: 1.68;
    color: #111;
}
h1.book-title {
    font-size: 2.1em;
    text-align: center;
    margin-top: 22%;
    margin-bottom: 6%;
    letter-spacing: 2px;
    border-bottom: 2px solid #222;
    padding-bottom: 18px;
}
p.book-subtitle {
    font-size: 1.15em;
    text-align: center;
    color: #444;
    margin-bottom: 18%;
}
.cover-date {
    text-align: center;
    font-size: 1.0em;
    color: #555;
}
h2 {
    font-size: 1.45em;
    border-bottom: 1.5px solid #333;
    padding-bottom: 8px;
    margin-top: 1.2em;
    margin-bottom: 0.8em;
    page-break-before: always;
}
.section-header {
    font-size: 1.2em;
    font-weight: bold;
    margin-top: 1.3em;
    margin-bottom: 0.5em;
    padding-left: 8px;
    border-left: 4px solid #333;
}
.sub-header {
    font-size: 1.15em;
    font-weight: bold;
    margin-top: 1.4em;
    margin-bottom: 0.5em;
    border-bottom: 1px dashed #666;
    padding-bottom: 4px;
}
.meta-box {
    background-color: #efefef;
    border-left: 4px solid #444;
    padding: 10px 12px;
    margin: 12px 0 16px 0;
    font-size: 0.95em;
}
.meta-box p {
    margin: 4px 0;
}
p.item-field {
    margin: 5px 0;
    text-indent: 0;
}
p {
    margin: 6px 0;
    text-align: justify;
}
a {
    color: #111;
    text-decoration: underline;
    word-break: break-all;
}
"""

os.makedirs("output", exist_ok=True)
epub_file = "output/DailyNews.epub"

print(f"正在制作精装 EPUB: {epub_file} ...")
with zipfile.ZipFile(epub_file, 'w', zipfile.ZIP_DEFLATED) as z:
    z.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
    z.writestr('META-INF/container.xml', '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>''')

    z.writestr('OEBPS/content.opf', f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>每日精选资讯合订本 ({date_str})</dc:title>
    <dc:creator>AI 定时晨报</dc:creator>
    <dc:language>zh-CN</dc:language>
    <dc:date>{date_str}</dc:date>
    <dc:identifier id="BookId">urn:uuid:dailynews-{date_str}</dc:identifier>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="style" href="style.css" media-type="text/css"/>
    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="cover"/>
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
  </spine>
  <guide>
    <reference type="toc" title="目录" href="cover.xhtml"/>
  </guide>
</package>''')

    z.writestr('OEBPS/toc.ncx', f'''<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:uuid:dailynews-{date_str}"/>
    <meta name="dtb:depth" content="2"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>每日精选资讯合订本 ({date_str})</text></docTitle>
  <navMap>
    <navPoint id="np-1" playOrder="1">
      <navLabel><text>精装扉页 · 目录</text></navLabel>
      <content src="cover.xhtml"/>
    </navPoint>
    <navPoint id="np-2" playOrder="2">
      <navLabel><text>一、 智能建筑资讯晨报</text></navLabel>
      <content src="chapter1.xhtml"/>
    </navPoint>
    <navPoint id="np-3" playOrder="3">
      <navLabel><text>二、 AI 晨报</text></navLabel>
      <content src="chapter2.xhtml"/>
    </navPoint>
  </navMap>
</ncx>''')

    z.writestr('OEBPS/style.css', CSS_STYLE)

    z.writestr('OEBPS/cover.xhtml', f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>每日精选资讯合订本</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <h1 class="book-title">每日精选资讯合订本</h1>
  <p class="book-subtitle">专属定制晨报</p>
  <p class="cover-date">{date_str} · {weekday_str}</p>
  
  <div style="margin-top: 30%; border-top: 1px solid #777; padding-top: 15px;">
    <h3>【今日目录导航】</h3>
    <p>📖 <a href="chapter1.xhtml">一、 智能建筑资讯晨报</a></p>
    <p>🤖 <a href="chapter2.xhtml">二、 AI 晨报</a></p>
  </div>
</body>
</html>''')

    z.writestr('OEBPS/chapter1.xhtml', f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>智能建筑资讯晨报</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  {content_building}
</body>
</html>''')

    z.writestr('OEBPS/chapter2.xhtml', f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>AI 晨报</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  {content_ai}
</body>
</html>''')

print("精装合订本编译完成！")
