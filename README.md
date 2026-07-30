# HA AI Maintainer

Saját, biztonságos AI-karbantartó alap Home Assistant OS rendszerhez.

A jelenlegi verzió megfigyel, kérésre AI-diagnózist készít, ismert hibákhoz
GitHub Codex-javítást tud indítani, és kikapcsolt alapállapotú, strukturált
OpenAI fájljavítási folyamatot biztosít:

- lekéri a Home Assistant entitásainak állapotát;
- összesíti az `unavailable` és `unknown` entitásokat;
- a Home Assistant WebSocket API-ján lekéri a legutóbbi rendszerhibákat és
  figyelmeztetéseket;
- helyben, egy Ingress felületen mutatja az eredményt;
- külön mutatja az egyedi naplóhibákat és azok összes ismétlődését;
- domain és naplóforrás szerint csoportosítja a leggyakoribb problémákat;
- az érzékeny adatnak tűnő naplórészleteket megjelenítés előtt kitakarja.
- külön jóváhagyás után a meglévő Home Assistant OpenAI AI Task entitással
  magyar nyelvű, prioritásos hibadiagnózist készít.
- a helyben, determinisztikusan felismert és előre engedélyezett hibákat a
  felhasználó külön jóváhagyása után GitHub Codex-workflow-nak adja át;
- a Codex elkülönített jobban készít patch-et, egy második job pedig draft
  pull requestet nyit.
- az OpenAI javítási modell kizárólag az engedélyezett Home Assistant-fájlok
  szűrt másolatából készíthet strukturált módosítási tervet, helyi parancsfuttatás
  nélkül;
- a legutóbbi AI-diagnózisból külön jóváhagyással közvetlenül indítható helyi
  fájljavítási javaslat, amely megkapja a korlátozott és kitakart bizonyítékot;
- minden javítás előtt szűkíthető az adott futásba bevont fájlok és könyvtárak
  köre;
- az élő fájlokra csak külön második jóváhagyással, fájlszintű mentéssel és
  Home Assistant konfiguráció-ellenőrzéssel kerülhet a módosítás.
- külön vizsgálattal megkeresi az árva, illetve a beállított ideje folyamatosan
  `unavailable` entitásokat; csak kézi kijelölés és törlés előtti
  újraellenőrzés után távolítja el őket a regiszterből.

## Biztonsági határok

Az automatikus vizsgálat:

- nem vezérel eszközöket;
- automatikusan nem küld adatot külső szolgáltatáshoz;
- az AI-elemzés csak a felhasználó megerősítése után hívja az
  `ai_task.generate_data` műveletet;
- az AI-nak nem küldi el a problémás entitások nevét vagy azonosítóját;
- legfeljebb 15, korábban kitakart naplómintát és összesített számlálókat küld;
- az AI-fájljavítás nem automatikus: a javaslat elkészítéséhez és az élő
  fájlokra alkalmazásához külön böngészős megerősítés szükséges;
- a GitHubnak csak a rögzített javításazonosítót küldi, naplót, entitásadatot és
  Home Assistant-konfigurációt nem;
- a futó Home Assistantot és az eszközöket a GitHubon futó Codex nem
  módosíthatja.
- az entitástörlés nem AI-döntés: az alkalmazás determinisztikusan ellenőrzi a
  regisztert, nem jelöl ki semmit automatikusan, és a törléshez külön
  megerősítést kér.

A `0.4.0` verzió írhatóan csatolja a Home Assistant konfigurációs mappáját a
konténer `/homeassistant` útvonalára, ezért ez kézi jóváhagyást igénylő
breaking update. A helyi javítás ettől még alapból ki van kapcsolva. Bekapcsolva
is három külön megerősítési pontot használ: javaslatkészítés, alkalmazás és
visszaállítás. Az OpenAI kizárólag a kijelölt, méretkorlátozott fájlmásolatokat
kapja meg; az élő mappát nem. A `secrets.yaml`, `.storage`, adatbázisok, kulcsfájlok,
rejtett könyvtárak és szimbolikus hivatkozások tiltottak.

A `0.5.0` entitástisztítása a Home Assistant belső WebSocket API-ját használja,
és nem küld entitásadatot az OpenAI-nak vagy a GitHubnak. A törlés nem
visszavonható; csak olyan `unavailable` regiszterbejegyzés választható ki,
amely egy már nem létező konfigurációs bejegyzésre hivatkozik, vagy a Home
Assistant `last_changed` adata szerint legalább a beállított ideje
folyamatosan nem elérhető. Az app a jóváhagyás után, közvetlenül a törlés előtt
ismét elvégzi ugyanezt az ellenőrzést. A funkció alapból ki van kapcsolva;
használatához engedélyezni kell a **Régi és árva entitások törlése** beállítást.

Az első engedélyezett cél az `Mqbretrofit/ha-anthbot-map` túlméretes
térképattribútum-hibája.

## Telepítés

1. Home Assistantban nyisd meg a **Beállítások → Alkalmazások → Alkalmazásbolt**
   oldalt.
2. A jobb felső menüben válaszd a **Tárolók** lehetőséget.
3. Add hozzá:

   ```text
   https://github.com/Mqbretrofit/ha-ai-maintainer
   ```

4. Telepítsd a **HA AI Maintainer** alkalmazást.
5. Indítsd el, majd kapcsold be az oldalsáv megjelenítését.
6. Az AI-diagnózishoz legyen pontosan egy OpenAI AI Task entitás beállítva.

## OpenAI fájljavítás egyszeri beállítása

1. A **HA AI Maintainer → Konfiguráció** lapon kapcsold be a
   **OpenAI fájljavítás engedélyezése** lehetőséget.
2. Illeszd be az OpenAI Platform API-kulcsodat az
   **OpenAI API-kulcs a fájljavításhoz** mezőbe.
3. Ellenőrizd a javítható relatív útvonalak listáját. Alapból:
   `configuration.yaml`, `automations.yaml`, `scripts.yaml`, `scenes.yaml`,
   `templates.yaml`, `packages`, `dashboards` és `www`. Helyi egyedi
   integráció javításához külön felveheted a `custom_components` könyvtárat.
4. Mentsd a konfigurációt, majd indítsd újra az alkalmazást.

A felületen minden javítási kérés előtt kiválaszthatod, melyik engedélyezett
útvonal tartalma kerüljön a strukturált OpenAI-kérésbe. A nagy `dashboards` és `www` mappák
alapból nincsenek kijelölve, így kisebb az esélye a méretkorlát túllépésének.

A Home Assistant OpenAI-integrációjában tárolt kulcsot az alkalmazás nem tudja
kiolvasni, ezért a fájljavításhoz külön meg kell adni ugyanazt vagy egy erre a
célra létrehozott API-kulcsot.

## Codex-javítás egyszeri beállítása

1. Az `Mqbretrofit/ha-anthbot-map` GitHub-projektben add hozzá az OpenAI
   API-kulcsot `OPENAI_API_KEY` nevű Actions repository secretként.
2. Készíts csak erre a projektre érvényes, lejárattal rendelkező fine-grained
   GitHub tokent. A szükséges repository jogosultság: **Actions: Read and
   write**.
3. A HA AI Maintainer **Konfiguráció** lapján illeszd be a tokent a
   **GitHub workflow-token** mezőbe, mentsd, majd indítsd újra az alkalmazást.

A GitHub-token nem kerül az állapot API-ba vagy a felületre. Kizárólag az
előre rögzített `codex-repair.yml` workflow indítására használható.

Ha a hibanapló átmenetileg nem érhető el, az entitások állapotvizsgálata akkor
is megjelenik.

Az alkalmazás jelenleg kísérleti állapotú.
