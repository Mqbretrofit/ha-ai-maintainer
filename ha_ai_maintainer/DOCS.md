# HA AI Maintainer

Az alkalmazás a Home Assistant saját, belső REST- és WebSocket API-proxyján
keresztül rendszerállapot-összesítést készít. Az automatikus vizsgálat eszközt
nem vezérel és konfigurációt nem módosít. A `0.4.0` opcionális helyi
Codex-javítása kizárólag többlépcsős jóváhagyás után írhat engedélyezett
fájlokat. A `0.5.0` összeköti az AI-diagnózist a helyi Codex-javaslattal, és
külön jóváhagyásos árvaentitás-tisztítást ad.

A `0.5.1` verziótól az AI-diagnózis „Codexszel javítható” minősítése csak
tanács: a Codex a kijelölt fájlokat önállóan is ellenőrzi. Ha nem talál
biztonságosan javítható fájlhibát, az általános hibaüzenet helyett megjelenik
a konkrét indoklása és a még szükséges fájl vagy bizonyíték.

## Beállítások

### `scan_interval_minutes`

Az automatikus vizsgálatok közötti idő percben. Alapérték: `15`.

### `max_problem_entities`

Legfeljebb ennyi `unavailable` vagy `unknown` entitást jelenít meg.
Alapérték: `50`.

### `max_log_lines`

A rendszerhibák és figyelmeztetések legutóbbi legfeljebb ennyi bejegyzését
vizsgálja. Alapérték: `1000`.

### `redact_sensitive_data`

Kitakarja az API-kulcsnak, tokennek, jelszónak, e-mail-címnek, IP-címnek vagy
koordinátának tűnő értékeket. Alapérték: bekapcsolva.

### `github_token`

Opcionális, maszkolt beállítás. A Codex-javításhoz csak a kiválasztott
GitHub-projektre érvényes, lejárattal rendelkező fine-grained tokent használj,
**Actions: Read and write** repository jogosultsággal. Az alkalmazás a tokent
nem jeleníti meg, nem naplózza és nem adja át az OpenAI-nak.

### `entity_cleanup_enabled`

Az árva vagy régóta `unavailable` entitásregiszter-bejegyzések törlésének
főkapcsolója. Alapérték: kikapcsolva. A bekapcsolás önmagában nem töröl
semmit; külön jelöltvizsgálat, kézi kijelölés, böngészős megerősítés és
szerveroldali újraellenőrzés szükséges.

### `entity_cleanup_min_unavailable_days`

Aktív konfigurációs bejegyzéshez tartozó entitás csak akkor kerülhet a törlési
jelöltek közé, ha a Home Assistant aktuális `last_changed` időbélyege szerint
legalább ennyi napja folyamatosan `unavailable`. Alapérték: `30`, megengedett
tartomány: `7`–`3650` nap. A Home Assistant újraindítása megváltoztathatja ezt
az időbélyeget, ezért a feltétel szándékosan konzervatív.

### `local_repair_enabled`

A helyi Codex-javítás főkapcsolója. Alapérték: kikapcsolva. A bekapcsolás
önmagában nem módosít fájlt; minden javaslat, alkalmazás és visszaállítás külön
böngészős megerősítést kér.

### `openai_api_key`

Maszkolt OpenAI Platform API-kulcs a helyben futó Codex CLI-hez. A Home
Assistant OpenAI-integrációjában tárolt kulcs nem olvasható ki az alkalmazásból,
ezért itt külön kell megadni. A kulcs nem kerül naplóba vagy állapotválaszba.
A Codex futtatása előtt a CLI hitelesítési tárába kerül; a modell által
indított parancsok környezete nem kap API-kulcsot, `SUPERVISOR_TOKEN`-t vagy
GitHub-tokent.

### `local_repair_paths`

A `/homeassistant` mappán belüli relatív fájlok és könyvtárak, amelyek szűrt,
méretkorlátozott másolata bekerülhet a Codex izolált munkamappájába. Alapérték:

- `configuration.yaml`
- `automations.yaml`
- `scripts.yaml`
- `scenes.yaml`
- `templates.yaml`
- `packages`
- `dashboards`
- `www`

A listához külön hozzáadható például a `custom_components` könyvtár, így a
GitHubon kívüli, helyben telepített egyedi integrációk is javíthatók. A méret-
és fájlszámkorlát ezekre is érvényes.

A `secrets.yaml`, `.storage`, `.cloud`, adatbázisok, mentések, SSL- és
kulcsfájlok, rejtett útvonalak és szimbolikus hivatkozások akkor is tiltottak,
ha valaki megpróbálja felvenni őket a listába.

## Hálózat és adatkezelés

Az alkalmazás nem nyit hostportot, csak a Home Assistant Ingress felületén
érhető el. Az automatikus vizsgálat nem küld adatot külső szolgáltatásnak.

Az **AI-elemzés indítása** gomb külön megerősítést kér. Csak ezután hívja meg a
Home Assistant `ai_task.generate_data` műveletét a már beállított OpenAI AI Task
entitással. Az alkalmazás nem olvassa ki és nem tárolja az OpenAI API-kulcsot.

Az AI-nak elküldött csomag:

- összesített entitás- és naplószámlálókat;
- problémás domaineket és naplóforrásokat;
- legfeljebb 15, egyenként legfeljebb 900 karakteres, kitakart naplómintát
  tartalmaz.

A problémás entitások neve és azonosítója nem része az AI-csomagnak. A
naplószöveg megbízhatatlan bemenetként van megjelölve a prompt-injekció
kockázatának csökkentésére. Az AI válasza kizárólag javaslat, automatikus
javítás vagy Home Assistant-művelet nem követi.

A **Helyi Codex-javítás** külön adatfolyam. Csak az első megerősítés után jut
el az OpenAI-hoz a felhasználó feladatszövege és az engedélyezett
`local_repair_paths` alatt talált fájlok azon tartalma, amelyet a Codex a
feladat végrehajtásához elolvas. Napló, teljes entitáslista, `.storage`,
`secrets.yaml`, Supervisor-token és GitHub-token nem kerül ebbe a
munkamappába.

Ha a **Javítási javaslat készítése ebből a diagnózisból** gombot használod,
akkor a megerősítő ablakban jelzett módon a legutóbbi AI-válasz és az ahhoz
tartozó, legfeljebb 15 kitakart naplóminta is a helyi Codex bemenete lesz.
Ezek külön, megbízhatatlan bizonyítékblokként kerülnek a promptba. A Codexnek
minden állítást a kiválasztott fájlokban is ellenőriznie kell; hálózati,
kikapcsolt eszköz-, újrapárosítási, újraindítási és felhőhibára nem készíthet
kitalált fájlmódosítást.

Az árvaentitás-vizsgálat és -törlés nem küld adatot külső szolgáltatáshoz.
Kizárólag a Home Assistant belső WebSocket API-ján olvassa az aktuális
állapotokat, az entitásregisztert és a konfigurációs bejegyzések listáját.

## Helyi Codex-javítás

A helyi javítás két elkülönített fázisból áll:

1. **Javaslat készítése:** a felhasználó megadja a feladatot és jóváhagyja,
   hogy a feladat, valamint az engedélyezett fájlok szűrt másolata az OpenAI
   Codex szolgáltatásához kerüljön.
   A felület az adott futásra tovább szűkíti a konfigurációban engedélyezett
   útvonalakat; az API ezt a listát nem engedi kibővíteni.
2. A Codex egy `/data/local-repairs/<azonosító>/workspace` alatti Git
   munkamappában dolgozik. Az élő `/homeassistant` útvonalat nem kapja meg.
3. A Codex fájlrendszerprofilja alapból minden más fájl olvasását tiltja,
   csak a minimális futtatókörnyezetet engedi olvasni, és kizárólag az izolált
   workspace-ben enged írást. A modellparancsok hálózati hozzáférése tiltott.
4. Az alkalmazás elutasítja a javaslatot, ha a Codex új fájlt hoz létre, fájlt
   töröl vagy átnevez, nem engedélyezett fájlt módosít, 20-nál több fájlhoz nyúl,
   vagy túl nagy diffet készít.
5. A teljes diff megjelenik a helyi Ingress felületen. Az élő konfiguráció ekkor
   még változatlan.
6. **Alkalmazás:** külön jóváhagyás után az alkalmazás ellenőrzi, hogy az élő
   fájlok nem változtak-e a javaslat óta, majd fájlszintű mentést készít.
7. Az atomikusan cserélt fájlok után lefut a Home Assistant
   `/api/config/core/check_config` ellenőrzése. Hibánál az eredeti fájlok
   automatikusan visszaállnak.
8. Siker esetén a felület külön visszaállítási lehetőséget ad. Az alkalmazás
   soha nem indítja újra automatikusan a Home Assistantot, és nem vezérel
   eszközt.

A fájlszintű mentés az alkalmazás saját `/data` területén marad, és az
alkalmazás újraindítása után is elérhető. Ez nem teljes Home Assistant-backup;
nagyobb vagy kockázatosabb változtatás előtt továbbra is ajánlott teljes
rendszermentést készíteni.

## Árva entitások törlése

A **Törlési jelöltek keresése** művelet csak akkor jelöl egy bejegyzést, ha:

- aktuális állapota `unavailable`;
- szerepel a Home Assistant entitásregiszterében;
- nem üres `config_entry_id` értékkel rendelkezik; és
- a hivatkozott konfigurációs bejegyzés már nem létezik, vagy a Home Assistant
  `last_changed` időbélyege szerint az entitás legalább a beállított ideje
  folyamatosan `unavailable`.

Az aktív integrációhoz tartozó, rövidebb ideje offline eszközök, az `unknown`
állapotok és a `config_entry_id` nélküli YAML-entitások nem kerülnek a
jelöltlistába. A régóta offline, de aktív integrációhoz tartozó jelöltnél a
felület külön figyelmeztet, hogy az integráció később újra létrehozhatja.
A felület semmit nem jelöl ki automatikusan.

A kijelölt elemek törléséhez külön megerősítés kell. Az alkalmazás közvetlenül
a törlés előtt ismét lekéri mindhárom adatforrást, és a teljes műveletet
megtagadja, ha bármelyik kiválasztott elem már nem felel meg a feltételeknek.
Egyszerre legfeljebb 50 bejegyzés törölhető. A regisztertörléshez a Home
Assistant admin jogosultsága szükséges, nem készül róla visszaállítható mentés,
és egy később visszatérő integráció újra létrehozhatja az entitást.

Ez nem az AI döntése, és nem része a Codex fájljavításának.
Használat előtt az alkalmazás konfigurációjában külön be kell kapcsolni az
`entity_cleanup_enabled` opciót. A tartós unavailable küszöböt az
`entity_cleanup_min_unavailable_days` adja meg.

### Új alkalmazásjogosultság a 0.4.0 verzióban

A `homeassistant_config` mappa írhatóan, `/homeassistant` néven kerül a
konténerbe. Emiatt a `0.4.0` kézi jóváhagyást igénylő breaking update. A jogot
csak a külön jóváhagyott alkalmazási és visszaállítási lépés használja; a
diagnosztika és a Codex javaslatkészítése nem ír az élő mappába.

## GitHub Codex-javítás

A `0.3.0` verzió helyben felismeri az előre engedélyezett Anthbot Map
Recorder-hibát. A **Javítás készítése Codexszel** gomb:

1. külön megerősítést kér;
2. a GitHubnak kizárólag a `map_attributes_too_large` javításazonosítót küldi;
3. elindítja az `Mqbretrofit/ha-anthbot-map` projekt rögzített
   `codex-repair.yml` workflow-ját.

Napló, entitásazonosító, állapotadat és Home Assistant-konfiguráció nem része a
GitHub-kérésnek. A workflow első, csak olvasási repository-jogú jobja futtatja
a Codexet és patch-artifactot készít. A második job nem kap OpenAI API-kulcsot;
csak a patch-et alkalmazza, ellenőrzi, és draft pull requestet nyit. Sem a
workflow, sem a Codex nem fér hozzá a futó Home Assistanthoz.

Az `OPENAI_API_KEY` kulcsot a célprojekt GitHub Actions repository secretjei
között kell beállítani. Ez külön van a Home Assistant OpenAI-integrációjában
tárolt kulcstól, amelyet az alkalmazás nem tud és nem is próbál kiolvasni.

A `0.1.1` verzió a strukturált `system_log/list` WebSocket parancsot használja.
Ehhez nem kér új Home Assistant- vagy Supervisor-jogosultságot. Ha a napló nem
érhető el, az entitásvizsgálat eredménye továbbra is megjelenik.

A `0.1.2` verzió külön kezeli az egyedi naplóbejegyzések számát és azok összes
ismétlődését. A problémás entitásokat domain, a naplóbejegyzéseket forrás szerint
is összesíti. Entitást automatikusan nem hagy figyelmen kívül.

A `0.2.0` verzió kézi jóváhagyással AI-diagnózist készít a meglévő OpenAI AI
Task entitással. A `0.2.1` előnyben részesíti a szabványos
`ai_task.openai_ai_task` entitást, majd az egyetlen elérhető OpenAI AI Taskot.
A `0.2.2` az első használat előtti `unknown` állapotot is kiválaszthatónak
tekinti. Ha továbbra sem lehet egyértelműen választani, a hibaüzenet felsorolja
a talált azonosítókat.

## Hibaelhárítás

Ha a felület nem tölt be:

1. Nyisd meg az alkalmazás naplóját.
2. Ellenőrizd, hogy a Home Assistant teljesen elindult-e.
3. Indítsd újra a HA AI Maintainer alkalmazást.

Ha az AI-elemzés nem indul:

1. Ellenőrizd a **Beállítások → Eszközök és szolgáltatások → OpenAI** oldalon az
   OpenAI AI Task entitást.
2. Ellenőrizd az OpenAI API-egyenleget és használati korlátot.
3. Ha több OpenAI AI Task entitás van, ideiglenesen csak egyet hagyj
   engedélyezve.

Ha a helyi Codex-javaslat nem indul:

1. Ellenőrizd, hogy a `local_repair_enabled` be van-e kapcsolva.
2. Add meg az `openai_api_key` mezőt; az OpenAI-integráció meglévő kulcsa nem
   olvasható ki automatikusan.
3. Ellenőrizd, hogy a `local_repair_paths` legalább egy létező, nem tiltott
   YAML-, JSON-, JavaScript-, TypeScript-, Python-, CSS-, HTML- vagy Markdown-
   fájlt tartalmaz-e.
4. Nézd meg az alkalmazás naplóját Codex-hitelesítési, időtúllépési vagy
   sandboxhibáért.
