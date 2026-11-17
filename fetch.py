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
MAX_PAGE_FETCH = 40  # bir çalıştırmada yazar için en fazla bu kadar sayfa açılır
NOW = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def get(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r


def soup_of(url):
    # .content: ham veri. BeautifulSoup karakter kodunu sayfanın kendisinden okur.
    return BeautifulSoup(get(url).content, "html.parser")


def tr_title(s):
    """BÜYÜK HARFLİ adı Türkçe kurallarıyla 'Büyük Harfli' yapar."""
    def fix(w):
        w = w.replace("I", "ı").replace("İ", "i").lower()
        first = "İ" if w[:1] == "i" else w[:1].upper()
        return first + w[1:]
    return " ".join(fix(w) for w in s.split())


def page_author(url):
    """Yazı sayfasının <meta name="author"> alanından yazar adını okur."""
    try:
        soup = soup_of(url)
        for key in ("author", "articleAuthor"):
            tag = soup.find("meta", attrs={"name": key})
            if tag and tag.get("content"):
                return tag["content"].strip()
    except Exception:
        pass
    return ""


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
    soup = soup_of(src["url"])
    n_links = len(soup.find_all("a"))
    page_title = soup.title.string if soup.title else None
    print(f'  {src["name"]} sayfası: {n_links} link, başlık: {page_title}')
    link_re = re.compile(src["link_regex"])
    mode = src.get("author_from", "")
    names = {}  # slug -> düzgün yazar adı (Türkçe karakterli)
    if src.get("author_index_regex"):
        idx = re.compile(src["author_index_regex"])
        for a in soup.find_all("a", href=True):
            m = idx.search(urlparse(a["href"]).path)
            text = a.get_text(strip=True)
            low = text.lower()
            if "tüm" in low and "yazı" in low:   # "Tüm Yazıları" bağlantısı ad değildir
                continue
            if m and text:
                names.setdefault(m.group(1), text)

    # Aynı yazıya giden tüm linkleri grupla (sayfa sırasıyla)
    groups = {}
    current = None
    for el in soup.find_all(["a", "img"]):
        if el.name == "img":
            # Star: yazı linkinden hemen sonra gelen görselin alt metni yazar adıdır
            if (mode == "next_img_alt" and current and el.get("alt")
                    and not groups[current]["alt"]):
                groups[current]["alt"] = el["alt"].strip()
            continue
        if not el.get("href"):
            continue
        full = urljoin(src["url"], el["href"])
        m = link_re.search(urlparse(full).path)
        if not m:
            continue
        current = full
        g = groups.setdefault(
            full, {"slug": m.group(1), "texts": [], "title": "", "alt": "", "bold": ""})
        text = el.get_text(" ", strip=True)
        if text:
            g["texts"].append(text)
        g["title"] = g["title"] or (el.get("title") or "").strip()
        img = el.find("img")
        if img and img.get("alt") and not g["alt"]:
            g["alt"] = img["alt"].strip()
        bold = el.find(["strong", "b"])
        if bold and not g["bold"]:
            g["bold"] = bold.get_text(" ", strip=True)

    out = []
    for full, g in groups.items():
        texts, title = g["texts"],
