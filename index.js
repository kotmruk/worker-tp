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

// Mapowanie: klucz z URL -> ID produktu "na żywo" z vod.tvp.pl
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
    if (!productId || productId === "REPLACE_ME") {
      return new Response(
        `Brak skonfigurowanego ID dla "${key}" — uzupełnij CHANNELS w index.js (patrz README)`,
        { status: 404 }
      );
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

  // 1) product ID -> externalUid (ID playera)
  const prodRes = await fetch(
    `https://vod.tvp.pl/api/products/vods/${productId}?lang=pl&platform=BROWSER`,
    { headers: { "User-Agent": ua } }
  );
  if (!prodRes.ok) throw new Error(`products API zwróciło ${prodRes.status}`);
  const prod = await prodRes.json();
  const externalUid = prod.externalUid;
  if (!externalUid) throw new Error("brak externalUid w odpowiedzi products API");

  // 2) externalUid -> getTvpConfig (JSONP z linkami, w tym m3u8 z tokenem)
  const cfgRes = await fetch(
    `https://vod.tvp.pl/sess/TVPlayer2/api.php?id=${externalUid}&@method=getTvpConfig&@callback=cb`,
    { headers: { "User-Agent": ua, "Referer": "https://vod.tvp.pl/" } }
  );
  if (!cfgRes.ok) throw new Error(`getTvpConfig zwróciło ${cfgRes.status}`);
  const text = await cfgRes.text();

  // to JSONP: cb({...}) — wyciągamy sam JSON
  const jsonStr = text.slice(text.indexOf("(") + 1, text.lastIndexOf(")"));
  let cfg;
  try {
    cfg = JSON.parse(jsonStr);
  } catch {
    throw new Error("nie udało się sparsować odpowiedzi getTvpConfig — sprawdź format w devtoolsach");
  }

  // Kształt JSON-a bywa różny (content.files / formats / files) —
  // szukamy pierwszego wpisu, który wygląda na HLS.
  const candidates =
    cfg?.content?.files || cfg?.content?.formats || cfg?.files || cfg?.formats || [];

  const hls = candidates.find(
    (f) => (f.type && String(f.type).includes("m3u8")) || (f.url && f.url.includes(".m3u8"))
  );

  if (!hls || !hls.url) {
    throw new Error(
      "nie znaleziono m3u8 w konfiguracji — struktura JSON-a się różni, sprawdź surową odpowiedź (patrz README, sekcja debug)"
    );
  }

  return hls.url;
}
