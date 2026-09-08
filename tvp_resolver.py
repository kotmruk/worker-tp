#!/usr/bin/env python3
# tvp_resolver.py — lokalny resolver linków live TVP (zamiennik workera Cloudflare)
#
# Dlaczego lokalnie: TVP blokuje żądania z Cloudflare Workers (IP datacenter +
# poza Polską = geoblock/403). Ten skrypt robi dokładnie to samo co worker,
# ale uruchomiony na Twoim komputerze pyta TVP z Twojego zwykłego domowego IP.
#
# Uruchomienie:
#   pip install flask requests
#   python tvp_resolver.py
#
# Podpięcie w tv.m3u (adres zależy od tego, gdzie stoi VLC/Kodi względem tego skryptu):
#   - VLC na TYM SAMYM komputerze  -> http://127.0.0.1:8787/tvp2
#   - inne urządzenie w domowej sieci -> http://<lokalne-IP-tego-PC>:8787/tvp2
#
#   #EXTINF:-1 group-title="TVP",TVP2
#   http://127.0.0.1:8787/tvp2
#
#   #EXTINF:-1 group-title="TVP",TVP3 Kielce
#   http://127.0.0.1:8787/tvp3kielce

from flask import Flask, redirect
import requests

app = Flask(__name__)

CHANNELS = {
    "abc": "399704",         # TVP ABC
    "kobieta": "399701",     # TVP Kobieta
    "abc2": "399727",        # TVP ABC 2
    "alfa": "399726",        # TVP Alfa
    "tvp2": "399698",        # TVP 2
    "tvp3kielce": "399745",  # TVP 3 Kielce
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def resolve_m3u8(product_id: str) -> str:
    headers = {
        "User-Agent": UA,
        "Referer": "https://vod.tvp.pl/",
        "Origin": "https://vod.tvp.pl",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    }
    url = (f"https://vod.tvp.pl/api/products/{product_id}/videos/playlist"
           f"?lang=pl&platform=BROWSER&videoType=MOVIE")
    r = requests.get(url, headers=headers, timeout=10)

    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"playlist API zwróciło {r.status_code} (body nie jest JSON-em)")

    if data.get("code"):
        raise RuntimeError(f"playlist API zwróciło {r.status_code}, kod: {data['code']}")
    if not r.ok:
        raise RuntimeError(f"playlist API zwróciło {r.status_code}: {str(data)[:200]}")

    hls = (data.get("sources") or {}).get("HLS") or []
    if not hls or "src" not in hls[0]:
        raise RuntimeError("nie znaleziono linku HLS w odpowiedzi playlist API")

    return hls[0]["src"]


@app.route("/")
def index():
    lista = ", ".join("/" + k for k in CHANNELS)
    return f"TVP live resolver.\nDostępne: {lista}\n", 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/<key>")
def resolve(key):
    key = key.lower()
    debug = False
    if key.endswith("/debug"):
        key, debug = key[:-6].rstrip("/"), True

    product_id = CHANNELS.get(key)
    if not product_id:
        return f'Brak skonfigurowanego ID dla "{key}"', 404

    try:
        m3u8 = resolve_m3u8(product_id)
    except Exception as e:
        return f"Nie udało się rozwiązać streamu: {e}", 502

    if debug:
        return f"Rozwiązany link:\n{m3u8}\n", 200, {"Content-Type": "text/plain; charset=utf-8"}

    return redirect(m3u8, code=302)


if __name__ == "__main__":
    # host="0.0.0.0" -> dostępne też z innych urządzeń w domowej sieci
    app.run(host="0.0.0.0", port=8787)
