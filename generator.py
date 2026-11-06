# -*- coding: utf-8 -*-
import os
import sys
import re
import urllib.parse
import zipfile
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timezone, timedelta

# 获取北京时间 (UTC+8)
tz_cst = timezone(timedelta(hours=8))
now = datetime.now(tz_cst)
date_str = now.strftime("%Y-%m-%d")
weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
weekday_str = weekdays[now.weekday()]

gmail_user = os.environ.get("GMAIL_USER")
gmail_pwd = os.environ.get("GMAIL_APP_PASSWORD")

if not gmail_user or not gmail_pwd:
    print("错误：未找到 GMAIL_USER 或 GMAIL_APP_PASSWORD 环境变量！")
    sys.exit(1)

# 清理应用密码里的空格
gmail_pwd = gmail_pwd.replace(" ", "")

print(f"正在连接 Gmail ({gmail_user}) 获取最新晨报邮件...")
mail = imaplib.IMAP4_SSL("imap.gmail.com")
try:
    mail.login(gmail_user, gmail_pwd)
except Exception as e:
    print(f"Gmail 登录失败，请检查密码配置: {e}")
    sys.exit(1)

mail.select("INBOX")

# 获取最近的 20 封邮件
status, messages = mail.search(None, "ALL")
mail_ids = messages[0].split()
recent_ids = mail_ids[-20:]
recent_ids.reverse()

content_building_raw = ""
content_ai_raw = ""

def decode_mime_words(s):
    if not s:
        return ""
    decoded_fragments = decode_header(s)
    res = []
    for frag, encoding in decoded_fragments:
        if isinstance(frag, bytes):
            res.append(frag.decode(encoding or "utf-8", errors="replace"))
        else:
            res.append(str(frag))
    return "".join(res)

def extract_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get('Content-Disposition'))
            # 优先提取 text/plain 纯文本
            if ctype == 'text/plain' and 'attachment' not in cdispo:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode('utf-8', errors='replace')
        # 如果没有 text/plain，提取 html
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get('Content-Disposition'))
            if ctype == 'text/html' and 'attachment' not in cdispo:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode('utf-8', errors='replace')
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode('utf-8', errors='replace')
    return ""

for mid in recent_ids:
    status, data = mail.fetch(mid, "(RFC822)")
    for response_part in data:
        if isinstance(response_part, tuple):
            msg = email.message_from_bytes(response_part[1])
            subject = decode_mime_words(msg.get("Subject", ""))
            body = extract_body(msg)

            # 严格认准 [MUSE] 标识与对应专栏
            if "[MUSE]" in subject and "智能建筑资讯晨报" in subject and not content_building_raw:
                print(f"成功命中【智能建筑资讯晨报】邮件 (主题: {subject})")
                content_building_raw = body
            if "[MUSE]" in subject and "AI 晨报" in subject and not content_ai_raw:
                print(f"成功命中【AI 晨报】邮件 (主题: {subject})")
                content_ai_raw = body

    if content_building_raw and content_ai_raw:
        break

mail.close()
mail.logout()

if not content_building_raw:
    print("未在收件箱最近邮件中找到【智能建筑资讯晨报】，使用默认提示排版...")
    content_building_raw = f"# 智能建筑资讯晨报 · {date_str}（{weekday_str}）\n今日未检索到该邮件。"

if not content_ai_raw:
    print("未在收件箱最近邮件中找到【AI 晨报】，使用默认提示排版...")
    content_ai_raw = f"# AI 晨报 · {date_str}（{weekday_str}）\n今日未检索到该邮件。"

# 清理 XML 特殊符号与链接
def clean_xml_and_urls(text):
    text = re.sub(r'https?://l\.meta\.ai/\?u=([^&]+)&amp;[^"\s\)]+', lambda m: urllib.parse.unquote(m.group(1)), text)
    text = re.sub(r'https?://l\.meta\.ai/\?u=([^&]+)&[^"\s\)]+', lambda m: urllib.parse.unquote(m.group(1)), text)
    # 转义 &
    text = re.sub(r'&(?!(amp|lt|gt|quot|apos);)', '&amp;', text)
    return text

# 针对 Muse 真实邮件格式的精准转换器
def format_to_html(raw_text):
    # 去除可能存在的 HTML 标签
    raw_text = re.sub(r'<[^>]+>', '', raw_text)
    lines = raw_text.split('\n')
    html_lines = []
    in_meta_box = False

    for line in lines:
        l = line.strip()
        if not l:
            continue

        # 匹配大标题: # 智能建筑资讯晨报·2026-11-06（星期五）
        if l.startswith('# '):
            html_lines.append(f'<h2>{l[2:]}</h2>')
            continue

        # 匹配导读框
        if l.startswith('来源:') or l.startswith('来源：'):
            html_lines.append('<div class="meta-box">')
            html_lines.append(f'<p><strong>来源：</strong>{l[3:].strip()}</p>')
            in_meta_box = True
            continue
        if (l.startswith('今日一句话:') or l.startswith('今日一句话：')) and in_meta_box:
            html_lines.append(f'<p><strong>今日一句话：</strong>{l[6:].strip()}</p>')
            html_lines.append('</div>')
            in_meta_box = False
            continue

        # 匹配版块大类: **1. IBMS 智能建筑管理平台**
        section_match = re.match(r'^\*\*\s*([0-9]\..+?)\s*\*\*$', l)
        if section_match:
            html_lines.append(f'<div class="section-header">{section_match.group(1)}</div>')
            continue

        # 匹配具体条目标题: - **AutomatedBuildings：...** 或 1. **Nvke – ...**
        item_match = re.match(r'^(?:-\s*)?(?:[0-9]+\.\s*)?\*\*(.+?)\*\*$', l)
        if item_match and not l.startswith('**[0-9]'):
            html_lines.append(f'<div class="item-title">• {item_match.group(1)}</div>')
            continue

        # 匹配固定栏目: 模型官方博客速览, 开源与社区速览, 口径说明
        if any(h in l for h in ["模型官方博客速览", "开源与社区速览", "口径说明", "和你相关的"]):
            html_lines.append(f'<div class="sub-header">{l}</div>')
            continue

        # 处理正文加粗
        l = re.sub(r'\*\*([^\*]+)\*\*', r'<strong>\1</strong>', l)

        # 处理链接: 链接: https://...
        link_match = re.search(r'(https?://[^\s\)]+)', l)
        if link_match:
            raw_url = link_match.group(1)
            l = re.sub(r'https?://[^\s\)]+', f'<a href="{raw_url}">{raw_url}</a>', l)
            html_lines.append(f'<p class="source-link">{l}</p>')
            continue

        html_lines.append(f'<p>{l}</p>')

    if in_meta_box:
        html_lines.append('</div>')

    joined = "\n".join(html_lines)
    return clean_xml_and_urls(joined)

content_building = format_to_html(content_building_raw)
content_ai = format_to_html(content_ai_raw)

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
.item-title {
    font-size: 1.08em;
    font-weight: bold;
    margin-top: 1.0em;
    margin-bottom: 0.3em;
    color: #111;
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
.source-link {
    font-size: 0.88em;
    color: #444;
    word-break: break-all;
    margin: 4px 0 12px 0;
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
    <dc:creator>Muse 定时晨报</dc:creator>
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
  <p class="book-subtitle">MUSE 专属定制晨报</p>
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
