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
      return new Response("Nie udało się rozwiązać streamu: " + e.message, { status: 502 });
    }
  },
};

async function resolveM3u8(productId) {
  const ua =
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

  // Dokładnie ten endpoint, którego używa aktualny extractor TVP w yt-dlp
  // (yt_dlp/extractor/tvp.py, klasa TVPVODVideoIE) dla kanałów live:
  //   https://vod.tvp.pl/api/products/{id}/videos/playlist?lang=pl&platform=BROWSER&videoType=MOVIE
  const res = await fetch(
    `https://vod.tvp.pl/api/products/${productId}/videos/playlist?lang=pl&platform=BROWSER&videoType=MOVIE`,
    { headers: { "User-Agent": ua, "Referer": "https://vod.tvp.pl/" } }
  );
  if (!res.ok) throw new Error(`playlist API zwróciło ${res.status}`);

  const data = await res.json();
  const hlsUrl = data?.sources?.HLS?.[0]?.src;

  if (!hlsUrl) {
    throw new Error("nie znaleziono linku HLS w odpowiedzi playlist API");
  }

  return hlsUrl;
}
