# HA AI Maintainer

Saját, biztonságos AI-karbantartó alap Home Assistant OS rendszerhez.

A jelenlegi verzió megfigyel és kérésre AI-diagnózist készít:

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

## Biztonsági határok

Ez a verzió:

- nem vezérel eszközöket;
- nem írja és nem csatolja be a `/config` könyvtárat;
- automatikusan nem küld adatot külső szolgáltatáshoz;
- az AI-elemzés csak a felhasználó megerősítése után hívja az
  `ai_task.generate_data` műveletet;
- az AI-nak nem küldi el a problémás entitások nevét vagy azonosítóját;
- legfeljebb 15, korábban kitakart naplómintát és összesített számlálókat küld;
- nem készít automatikus javítást vagy pull requestet.

A Codex-kapcsolat egy következő verzióban kerül hozzáadásra, külön GitHub- és
jóváhagyási kapu mögött.

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

Ha a hibanapló átmenetileg nem érhető el, az entitások állapotvizsgálata akkor
is megjelenik.

Az alkalmazás jelenleg kísérleti állapotú.
