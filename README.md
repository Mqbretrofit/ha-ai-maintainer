# HA AI Maintainer

Saját, biztonságos AI-karbantartó alap Home Assistant OS rendszerhez.

A jelenlegi verzió megfigyel, kérésre AI-diagnózist készít, és ismert hibákhoz
jóváhagyásos Codex-javítást tud indítani:

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

## Biztonsági határok

Ez a verzió:

- nem vezérel eszközöket;
- nem írja és nem csatolja be a `/config` könyvtárat;
- automatikusan nem küld adatot külső szolgáltatáshoz;
- az AI-elemzés csak a felhasználó megerősítése után hívja az
  `ai_task.generate_data` műveletet;
- az AI-nak nem küldi el a problémás entitások nevét vagy azonosítóját;
- legfeljebb 15, korábban kitakart naplómintát és összesített számlálókat küld;
- a Codex-javítás nem automatikus: külön böngészős megerősítés és egy
  engedélyezett javítási cél szükséges;
- a GitHubnak csak a rögzített javításazonosítót küldi, naplót, entitásadatot és
  Home Assistant-konfigurációt nem;
- a futó Home Assistantot és az eszközöket a Codex nem módosíthatja.

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
