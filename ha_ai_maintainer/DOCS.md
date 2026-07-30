# HA AI Maintainer

Az alkalmazás a Home Assistant saját, belső REST- és WebSocket API-proxyján
keresztül rendszerállapot-összesítést készít. Eszközt nem vezérel és
konfigurációt nem módosít.

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

## Codex-javítás

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
