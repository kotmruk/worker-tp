# tvp-resolver

Worker (Cloudflare Workers, free tier, bez własnego serwera) rozwiązujący
aktualne, tokenowane linki m3u8 do kanałów live TVP. Deploy automatyczny
z GitHuba przez Actions.

ID kanałów już wpisane w `index.js`:
- TVP ABC → 399704
- TVP Kobieta → 399701
- TVP ABC 2 → 399727

## Krok 1 — załóż repo na GitHubie

1. Wejdź na github.com → **New repository** → nazwa np. `tvp-resolver` →
   Public albo Private (obojętnie, workflow zadziała tak samo) → Create.
2. Nie dodawaj README/gitignore przy tworzeniu — repo ma być puste,
   bo pliki wgrasz z tej paczki.

## Krok 2 — wgraj pliki (bez terminala, przez przeglądarkę)

1. Na stronie świeżo utworzonego, pustego repo kliknij
   **"uploading an existing file"**.
2. Przeciągnij tam `index.js`, `wrangler.toml`, `README.md`.
3. Osobno: w repo na GitHubie stwórz plik o ścieżce
   `.github/workflows/deploy.yml` (przy tworzeniu pliku wpisz w polu nazwy
   dokładnie `.github/workflows/deploy.yml` — GitHub sam zrobi foldery)
   i wklej do niego zawartość `deploy.yml` z paczki.
4. Commit.

(Jak wolisz z terminala: `git init`, `git add .`, `git commit -m "init"`,
`git remote add origin <adres-twojego-repo>.git`, `git push -u origin main`.)

## Krok 3 — podepnij Cloudflare (żeby Action miał gdzie deployować)

1. Załóż darmowe konto na cloudflare.com (nie trzeba karty).
2. W Cloudflare: **My Profile → API Tokens → Create Token** → szablon
   "Edit Cloudflare Workers" → Create → skopiuj token (widoczny tylko raz).
3. W repo na GitHubie: **Settings → Secrets and variables → Actions →
   New repository secret** → nazwa `CLOUDFLARE_API_TOKEN`, wartość: token z kroku 2.

## Krok 4 — deploy

Każdy push do brancha `main` (albo wgranie plików w kroku 2, jeśli robiłeś
to przez przeglądarkę na branchu main) uruchomi Action, który sam
zdeployuje workera pod adres:

`https://tvp-resolver.<twoja-subdomena>.workers.dev`

Subdomenę zobaczysz w Cloudflare dashboard → Workers & Pages, albo w logu
Action na GitHubie (zakładka **Actions** w repo → ostatni run → zobaczysz
output wranglera z pełnym adresem).

## Jak podpiąć w tv.m3u

```
#EXTINF:-1 group-title="Dzieci",TVP ABC
https://tvp-resolver.<twoja-subdomena>.workers.dev/abc

#EXTINF:-1 group-title="Dzieci",TVP ABC 2
https://tvp-resolver.<twoja-subdomena>.workers.dev/abc2

#EXTINF:-1 group-title="Lifestyle",TVP Kobieta
https://tvp-resolver.<twoja-subdomena>.workers.dev/kobieta
```

VLC/Kodi podążą za redirectem 302 i za każdym razem dostaną świeży token —
nie musisz już ręcznie aktualizować linków.

## Jeśli resolver rzuca błędem "nie znaleziono m3u8 w konfiguracji"

Struktura JSON-a z `getTvpConfig` bywa różna zależnie od kanału/wersji API.
Odpal w przeglądarce ręcznie:

```
https://vod.tvp.pl/sess/TVPlayer2/api.php?id=<externalUid>&@method=getTvpConfig&@callback=cb
```

(externalUid wyciągniesz z `https://vod.tvp.pl/api/products/vods/<ID>?lang=pl&platform=BROWSER`)
i zobacz jak faktycznie nazywa się pole z linkiem m3u8 — potem popraw
`candidates` w `resolveM3u8()` w `index.js`.
