# api/index.py — resolver TVP live na Vercel (Python/Flask serverless)
# Sam hosting (Vercel) nie jest blokowany geoblockiem, ale zapytania do
# vod.tvp.pl musza wyjsc z polskiego IP -> stad rotacja darmowych proxy PL.
# Proxy sa odpytywane rownolegle, bo Vercel (Hobby) ubija funkcje po ok. 10s.

import os
import time
import concurrent.futures
from flask import Flask, redirect
import requests

# Jesli ustawione (Vercel -> Project Settings -> Environment Variables),
# uzywany jest TYLKO ten proxy, bez odpytywania darmowej listy PL.
# Format: protocol://host:port  albo  protocol://user:pass@host:port
# protocol = http / https / socks4 / socks5
FIXED_PROXY_URL = os.environ.get("TVP_PROXY")

app = Flask(__name__)

CHANNELS = {
    "abc": "399704",
    "kobieta": "399701",
    "abc2": "399727",
    "alfa": "399726",
    "tvp2": "399698",
    "tvp3kielce": "399745",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

PL_PROXY_LIST_URL = "https://raw.githubusercontent.com/proxyscrape/free-proxy-list/main/proxies/countries/pl/data.json"

_cache = {"list": [], "fetched_at": 0}


def get_proxy_list():
    # cache w pamieci procesu - dziala tylko dopoki instancja jest "warm",
    # wiec i tak czasem odswieza sie od zera, ale to tanie (jeden GET)
    if time.time() - _cache["fetched_at"] > 300 or not _cache["list"]:
        r = requests.get(PL_PROXY_LIST_URL, timeout=5)
        r.raise_for_status()
        proxies = r.json()
        proxies.sort(key=lambda p: (-p.get("uptime_percent", 0), p.get("latency_ms", 99999)))
        _cache["list"] = proxies
        _cache["fetched_at"] = time.time()
    return _cache["list"]


def proxy_dict_for(p):
    addr = f"{p['protocol']}://{p['ip']}:{p['port']}"
    return {"http": addr, "https": addr}


def try_one_proxy(product_id, p):
    headers = {
        "User-Agent": UA,
        "Referer": "https://vod.tvp.pl/",
        "Origin": "https://vod.tvp.pl",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    }
    url = (f"https://vod.tvp.pl/api/products/{product_id}/videos/playlist"
           f"?lang=pl&platform=BROWSER&videoType=MOVIE")
    r = requests.get(url, headers=headers, proxies=proxy_dict_for(p), timeout=4)
    data = r.json()
    if data.get("code"):
        raise RuntimeError(f"kod: {data['code']}")
    hls = (data.get("sources") or {}).get("HLS") or []
    if not hls or "src" not in hls[0]:
        raise RuntimeError("brak linku HLS")
    return hls[0]["src"]


def _get_playlist(product_id, proxies):
    headers = {
        "User-Agent": UA,
        "Referer": "https://vod.tvp.pl/",
        "Origin": "https://vod.tvp.pl",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    }
    url = (f"https://vod.tvp.pl/api/products/{product_id}/videos/playlist"
           f"?lang=pl&platform=BROWSER&videoType=MOVIE")
    r = requests.get(url, headers=headers, proxies=proxies, timeout=8)
    data = r.json()
    if data.get("code"):
        raise RuntimeError(f"kod: {data['code']}")
    hls = (data.get("sources") or {}).get("HLS") or []
    if not hls or "src" not in hls[0]:
        raise RuntimeError("brak linku HLS")
    return hls[0]["src"]


def resolve_m3u8(product_id: str) -> str:
    if FIXED_PROXY_URL:
        proxies = {"http": FIXED_PROXY_URL, "https": FIXED_PROXY_URL}
        return _get_playlist(product_id, proxies)

    candidates = get_proxy_list()[:12]
    if not candidates:
        raise RuntimeError("pusta lista proxy PL")

    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates)) as ex:
        futures = {ex.submit(try_one_proxy, product_id, p): p for p in candidates}
        try:
            for fut in concurrent.futures.as_completed(futures, timeout=8):
                p = futures[fut]
                try:
                    return fut.result()
                except Exception as e:
                    errors.append(f"{p['ip']}:{p['port']} -> {e}")
                    continue
        except concurrent.futures.TimeoutError:
            pass

    raise RuntimeError("zadne z probowanych proxy PL nie zadzialalo: " + "; ".join(errors[:5]))


@app.route("/")
def index():
    lista = ", ".join("/" + k for k in CHANNELS)
    return f"TVP live resolver (Vercel, auto-proxy PL).\nDostepne: {lista}\n", 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/<key>")
def resolve(key):
    key = key.lower()
    product_id = CHANNELS.get(key)
    if not product_id:
        return f'Brak skonfigurowanego ID dla "{key}"', 404

    try:
        m3u8 = resolve_m3u8(product_id)
    except Exception as e:
        return f"Nie udalo sie rozwiazac streamu: {e}", 502

    return redirect(m3u8, code=302)
