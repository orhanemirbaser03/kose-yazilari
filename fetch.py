"""sources.json'daki siteleri tarar, articles.json üretir.
Sadece başlık, yazar, tarih ve link saklanır; yazı metni kopyalanmaz."""
import json, re, datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (kisisel kose yazisi okuyucu)"}
KEEP_DAYS = 30
NOW = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def get(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r


def from_rss(src):
    root = ET.fromstring(get(src["url"]).content)
    dc = {"dc": "http://purl.org/dc/elements/1.1/"}
    out = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        if src.get("link_filter") and not re.search(src["link_filter"], link):
            continue
        try:
            date = parsedate_to_datetime(it.findtext("pubDate")).isoformat()
        except Exception:
            date = NOW
        out.append({
            "title": (it.findtext("title") or "").strip(),
            "link": link,
            "author": (it.findtext("dc:creator", namespaces=dc)
                       or it.findtext("author") or "").strip(),
            "date": date,
        })
    return out
    


def dup_prefix(s):
    """'A ... A' biçimindeki metinde baştaki ve sondaki aynı kelimeleri bulur."""
    w = s.split()
    for k in range(len(w) // 2, 0, -1):
        if w[:k] == w[-k:]:
            return " ".join(w[:k]), " ".join(w[k:len(w) - k])
    return "", s


def from_html(src):
    soup = BeautifulSoup(get(src["url"]).text, "html.parser")
    link_re = re.compile(src["link_regex"])
    names = {}  # slug -> düzgün yazar adı (Türkçe karakterli)
    if src.get("author_index_regex"):
        idx = re.compile(src["author_index_regex"])
        for a in soup.find_all("a", href=True):
            m = idx.search(urlparse(a["href"]).path)
            text = a.get_text(strip=True)
            if m and text:
                names.setdefault(m.group(1), text)

    # Aynı yazıya giden tüm linkleri grupla
    groups = {}
    for a in soup.find_all("a", href=True):
        full = urljoin(src["url"], a["href"])
        m = link_re.search(urlparse(full).path)
        if not m:
            continue
        g = groups.setdefault(full, {"slug": m.group(1), "texts": [], "title": ""})
        text = a.get_text(" ", strip=True)
        if text:
            g["texts"].append(text)
        g["title"] = g["title"] or (a.get("title") or "").strip()

    mode = src.get("author_from", "")
    out = []
    for full, g in groups.items():
        texts, title = g["texts"], g["title"]
        text = texts[0] if texts else ""
        author = names.get(g["slug"], "")
        if mode == "link_pair" and len(texts) >= 2:
            author, title = texts[0], texts[1]          # 1. link yazar, 2. link başlık
        elif mode == "before_title" and title and title in text:
            author = text[: text.find(title)].strip() or author
        elif mode == "text":
            if title and text.endswith(title):
                author = dup_prefix(text[: -len(title)].strip())[0] or author
            elif not title:
                t, a2 = dup_prefix(text)                # "Başlık Yazar Başlık"
                if t:
                    title, author = t, a2
        title = title or text
        if not author:
            author = re.sub(r"-\d+$", "", g["slug"]).replace("-", " ").title()
        if not title:
            continue
        out.append({"title": title, "link": full, "author": author, "date": NOW})
    return out


PARSERS = {"rss": from_rss, "html": from_html}


def main():
    sources = json.load(open("sources.json", encoding="utf-8"))
    try:
        old = json.load(open("articles.json", encoding="utf-8"))["articles"]
    except Exception:
        old = []
    by_link = {a["link"]: a for a in old}  # eski kayıtlar (ilk görülme tarihi korunur)

    for src in sources:
        try:
            items = PARSERS[src["type"]](src)
            print(f'{src["name"]}: {len(items)} yazı')
        except Exception as e:
            print(f'{src["name"]}: HATA {e}')
            continue
        for it in items:
            if it["link"] and it["title"]:
                it["source"] = src["name"]
                by_link.setdefault(it["link"], it)

    limit = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    arts = sorted((a for a in by_link.values() if a["date"] >= limit),
                  key=lambda a: a["date"], reverse=True)
    json.dump({"updated": NOW, "articles": arts},
              open("articles.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
