```python
# api/index.py
# Resolver TVP live na Vercel (Python/Flask)
#
# Vercel -> darmowe polskie proxy -> vod.tvp.pl -> link HLS
#
# Ważne:
# - lista proxy pochodzi z ProxyScrape na GitHubie
# - używamy tylko proxy HTTP/HTTPS, które mogą obsługiwać CONNECT
# - "https" z listy traktujemy jako proxy HTTP z tunelem CONNECT
#   (nie jako HTTPS proxy), bo tak działają typowe wpisy z takich list
# - SOCKS4/SOCKS5 są pomijane, żeby nie wymagać PySocks
# - proxy są testowane równolegle
# - pierwszy poprawny link HLS wygrywa
#
# Endpointy:
#   /abc
#   /kobieta
#   /abc2
#   /alfa
#   /tvp2
#   /tvp3kielce

import time
import concurrent.futures

from flask import Flask, redirect
import requests


app = Flask(__name__)


# ------------------------------------------------------------
# TVP product IDs
# ------------------------------------------------------------

CHANNELS = {
    "abc": "399704",
    "kobieta": "399701",
    "abc2": "399727",
    "alfa": "399726",
    "tvp2": "399698",
    "tvp3kielce": "399745",
}


# ------------------------------------------------------------
# HTTP headers
# ------------------------------------------------------------

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ------------------------------------------------------------
# Proxy list
# ------------------------------------------------------------

PL_PROXY_LIST_URL = (
    "https://raw.githubusercontent.com/"
    "proxyscrape/free-proxy-list/main/"
    "proxies/countries/pl/data.json"
)


# Cache żyje tak długo, jak długo Vercel utrzymuje warm instance.
_cache = {
    "list": [],
    "fetched_at": 0,
}


# ------------------------------------------------------------
# Pobieranie listy proxy
# ------------------------------------------------------------

def get_proxy_list():
    now = time.time()

    # Odświeżaj co 5 minut.
    if _cache["list"] and now - _cache["fetched_at"] < 300:
        return _cache["list"]

    try:
        r = requests.get(
            PL_PROXY_LIST_URL,
            timeout=2.5,
            headers={
                "User-Agent": UA,
                "Accept": "application/json",
            },
        )
        r.raise_for_status()

        data = r.json()

        if not isinstance(data, list):
            raise RuntimeError("lista proxy ma nieprawidłowy format")

        valid = []

        for p in data:
            if not isinstance(p, dict):
                continue

            ip = p.get("ip")
            port = p.get("port")
            protocol = str(p.get("protocol", "")).lower()

            if not ip or not port:
                continue

            # Nie potrzebujemy SOCKS.
            if protocol not in ("http", "https"):
                continue

            try:
                port = int(port)
            except (TypeError, ValueError):
                continue

            if not (1 <= port <= 65535):
                continue

            valid.append({
                "ip": str(ip),
                "port": port,
                "protocol": protocol,
                "uptime_percent": float(
                    p.get("uptime_percent", 0) or 0
                ),
                "latency_ms": float(
                    p.get("latency_ms", 99999) or 99999
                ),
            })

        # Najpierw najwyższy uptime, potem najniższe opóźnienie.
        valid.sort(
            key=lambda p: (
                -p["uptime_percent"],
                p["latency_ms"],
            )
        )

        if not valid:
            raise RuntimeError("brak użytecznych proxy HTTP/HTTPS")

        _cache["list"] = valid
        _cache["fetched_at"] = now

        return valid

    except Exception:
        # Jeżeli mamy starą listę, lepiej użyć jej niż wywalić resolver.
        if _cache["list"]:
            return _cache["list"]

        raise


# ------------------------------------------------------------
# Proxy
# ------------------------------------------------------------

def proxy_dict_for(proxy):
    """
    Darmowe listy często oznaczają proxy jako "https",
    ale oznacza to zazwyczaj możliwość obsługi HTTPS przez CONNECT.

    Dla requests poprawny wariant w takim przypadku to:

        http://IP:PORT

    jako proxy zarówno dla HTTP, jak i HTTPS.

    Nie robimy więc:

        https://IP:PORT

    ponieważ wtedy requests próbuje zestawić TLS
    bezpośrednio z serwerem proxy.
    """

    addr = f"http://{proxy['ip']}:{proxy['port']}"

    return {
        "http": addr,
        "https": addr,
    }


# ------------------------------------------------------------
# URL TVP
# ------------------------------------------------------------

def playlist_url(product_id):
    return (
        f"https://vod.tvp.pl/api/products/{product_id}/videos/playlist"
        f"?lang=pl&platform=BROWSER&videoType=MOVIE"
    )


# ------------------------------------------------------------
# Jedna próba przez jedno proxy
# ------------------------------------------------------------

def try_one_proxy(product_id, proxy):
    headers = {
        "User-Agent": UA,
        "Referer": "https://vod.tvp.pl/",
        "Origin": "https://vod.tvp.pl",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    }

    url = playlist_url(product_id)

    r = requests.get(
        url,
        headers=headers,
        proxies=proxy_dict_for(proxy),
        timeout=(1.5, 2.8),
        allow_redirects=True,
    )

    # Najpierw sprawdzamy status.
    if not r.ok:
        try:
            data = r.json()
            code = data.get("code")

            if code:
                raise RuntimeError(
                    f"HTTP {r.status_code}, kod: {code}"
                )

            raise RuntimeError(
                f"HTTP {r.status_code}"
            )

        except ValueError:
            raise RuntimeError(
                f"HTTP {r.status_code}, odpowiedź nie jest JSON-em"
            )

    # JSON
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(
            "TVP zwróciło odpowiedź, która nie jest JSON-em"
        )

    # TVP może zwrócić kod błędu mimo HTTP 200.
    if data.get("code"):
        raise RuntimeError(
            f"kod: {data['code']}"
        )

    # Szukamy HLS.
    sources = data.get("sources") or {}
    hls = sources.get("HLS") or []

    if not isinstance(hls, list) or not hls:
        raise RuntimeError("brak źródeł HLS")

    for source in hls:
        if not isinstance(source, dict):
            continue

        src = source.get("src")

        if isinstance(src, str) and src.startswith(("http://", "https://")):
            return src

    raise RuntimeError("brak poprawnego linku HLS")


# ------------------------------------------------------------
# Rozwiązywanie streamu
# ------------------------------------------------------------

def resolve_m3u8(product_id):
    proxies = get_proxy_list()

    if not proxies:
        raise RuntimeError("pusta lista proxy PL")

    # Nie bierzemy tylko 12.
    # Darmowe proxy często umierają pojedynczo, więc większa pula
    # zwiększa szansę znalezienia działającego.
    candidates = proxies[:24]

    errors = []

    # Maksymalnie około 7 sekund na próby.
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(candidates)
    ) as executor:

        future_map = {
            executor.submit(
                try_one_proxy,
                product_id,
                proxy
            ): proxy
            for proxy in candidates
        }

        try:
            for future in concurrent.futures.as_completed(
                future_map,
                timeout=7.0,
            ):
                proxy = future_map[future]

                try:
                    m3u8 = future.result()

                    # Mamy zwycięzcę.
                    return m3u8

                except Exception as e:
                    errors.append(
                        f"{proxy['ip']}:{proxy['port']} -> {e}"
                    )

        except concurrent.futures.TimeoutError:
            pass

    if errors:
        details = "; ".join(errors[:8])
        raise RuntimeError(
            "żadne z testowanych proxy PL nie zadziałało: "
            + details
        )

    raise RuntimeError(
        "żadne z testowanych proxy PL nie odpowiedziało"
    )


# ------------------------------------------------------------
# Strona główna
# ------------------------------------------------------------

@app.route("/")
def index():
    lista = ", ".join(
        "/" + key
        for key in CHANNELS
    )

    return (
        "TVP live resolver (Vercel, auto-proxy PL).\n"
        f"Dostępne: {lista}\n"
    ), 200, {
        "Content-Type": "text/plain; charset=utf-8"
    }


# ------------------------------------------------------------
# Resolver kanału
# ------------------------------------------------------------

@app.route("/<key>")
def resolve(key):
    key = key.lower().strip("/")

    product_id = CHANNELS.get(key)

    if not product_id:
        return (
            f'Brak skonfigurowanego ID dla "{key}"',
            404,
        )

    try:
        m3u8 = resolve_m3u8(product_id)

    except Exception as e:
        return (
            f"Nie udało się rozwiązać streamu: {e}",
            502,
        )

    # Przekazujemy klienta bezpośrednio na HLS.
    return redirect(m3u8, code=302)


# ------------------------------------------------------------
# Lokalny start (opcjonalny)
# ------------------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8787,
        debug=False,
    )
```
