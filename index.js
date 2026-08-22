// index.js — Cloudflare Worker: resolver linków live TVP
//
// Idea: TVP nie daje stałego m3u8 — link jest tokenowany i wygasa.
// Ten worker przy KAŻDYM odtwarzaniu na nowo pyta TVP o świeży link
// i robi redirect 302. Ty w swojej playliście (tv.m3u) wpisujesz
// stały adres workera, np.:
//
//   #EXTINF:-1 group-title="Dzieci",TVP ABC
//   https://tvp-resolver.<twoja-subdomena>.workers.dev/abc
//
// VLC/Kodi podążą za redirectem i dostaną aktualny token.

// Mapowanie: klucz z URL -> ID produktu "live" z vod.tvp.pl
// (widoczne w adresie strony, np. vod.tvp.pl/live,1/tvp-abc,399704 -> 399704)
const CHANNELS = {
  abc: "399704", // TVP ABC
  kobieta: "399701", // TVP Kobieta
  abc2: "399727", // TVP ABC 2
};

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const key = url.pathname.replace(/^\//, "").toLowerCase();

    if (key === "") {
      return new Response(
        "TVP live resolver.\nDostępne: " + Object.keys(CHANNELS).map(k => "/" + k).join(", "),
        { status: 200, headers: { "content-type": "text/plain; charset=utf-8" } }
      );
    }

    const productId = CHANNELS[key];
    if (!productId) {
      return new Response(`Brak skonfigurowanego ID dla "${key}"`, { status: 404 });
    }

    try {
      const m3u8 = await resolveM3u8(productId);
      return Response.redirect(m3u8, 302);
    } catch (e) {
      // Zwracamy błąd z kodem 502 i krótką wiadomością — w logach wyrzucamy szczegóły
      return new Response("Nie udało się rozwiązać streamu: " + e.message, { status: 502 });
    }
  },
};

async function resolveM3u8(productId) {
  const ua =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

  // Endpoint używany przez extractor yt-dlp dla live:
  const endpoint = `https://vod.tvp.pl/api/products/${productId}/videos/playlist?lang=pl&platform=BROWSER&videoType=MOVIE`;

  const res = await fetch(endpoint, {
    headers: {
      "User-Agent": ua,
      "Referer": "https://vod.tvp.pl/",
      // Drobne nagłówki pomagające otrzymać JSON zamiast np. JSONP/HTML
      "Accept": "application/json, text/javascript, */*; q=0.01",
      "X-Requested-With": "XMLHttpRequest",
    },
  });

  if (!res.ok) throw new Error(`playlist API zwróciło ${res.status}`);

  let data;
  const text = await res.text();

  // Spróbuj sparsować jako JSON; jeśli to JSONP — wyciągnij część między nawiasami
  try {
    data = JSON.parse(text);
  } catch (e) {
    // JSON.parse failed — try to extract JSON from possible JSONP like: callback({...})
    const jsonMatch = text.match(/^[^\(]*\((\{[\s\S]*\})\)\s*;?$/);
    if (jsonMatch) {
      try {
        data = JSON.parse(jsonMatch[1]);
      } catch (e2) {
        throw new Error('nie można sparsować JSONP z odpowiedzi playlist API');
      }
    } else {
      throw new Error('playlist API nie zwróciło JSON-a');
    }
  }

  // Najpierw sprawdź dobrze znane miejsca
  const hlsCandidates = [];

  // helper: bezpieczny getter
  const get = (obj, path) => path.split('.').reduce((acc, p) => (acc && acc[p] !== undefined ? acc[p] : undefined), obj);

  // typowe miejsca
  const maybe1 = get(data, 'sources.HLS');
  if (Array.isArray(maybe1) && maybe1.length) hlsCandidates.push(maybe1[0].src || maybe1[0].file || maybe1[0].url);

  const maybe2 = get(data, 'sources.hls');
  if (Array.isArray(maybe2) && maybe2.length) hlsCandidates.push(maybe2[0].src || maybe2[0].file || maybe2[0].url);

  // niektóre odpowiedzi mają struktury: data.videos[*].sources
  if (Array.isArray(data.videos)) {
    for (const v of data.videos) {
      const s = v?.sources?.HLS || v?.sources?.hls;
      if (Array.isArray(s) && s.length) hlsCandidates.push(s[0].src || s[0].file || s[0].url);
    }
  }

  // fallback: rekurencyjne szukanie pierwszego pola zawierającego m3u8
  const found = findFirstM3u8(data);
  if (found) hlsCandidates.push(found);

  const hlsUrl = hlsCandidates.find(u => typeof u === 'string' && u.includes('.m3u8'));

  if (!hlsUrl) {
    // Dla debugu zwracamy informację o kluczach najwyższego poziomu (nie cały dump)
    const topKeys = Object.keys(data || {}).slice(0, 20).join(', ');
    throw new Error(`nie znaleziono linku HLS w odpowiedzi playlist API, top-level keys: ${topKeys}`);
  }

  return hlsUrl;
}

function findFirstM3u8(obj, seen = new WeakSet()) {
  if (!obj || typeof obj === 'string') {
    if (typeof obj === 'string' && obj.includes('.m3u8')) return obj;
    return null;
  }
  if (typeof obj !== 'object') return null;
  if (seen.has(obj)) return null;
  seen.add(obj);
  for (const k of Object.keys(obj)) {
    const v = obj[k];
    if (typeof v === 'string' && v.includes('.m3u8')) return v;
    if (Array.isArray(v)) {
      for (const item of v) {
        const r = findFirstM3u8(item, seen);
        if (r) return r;
      }
    } else if (typeof v === 'object') {
      const r = findFirstM3u8(v, seen);
      if (r) return r;
    }
  }
  return null;
}
