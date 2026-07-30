# HA AI Maintainer

Saját, biztonságos AI-karbantartó alap Home Assistant OS rendszerhez.

Az első, `0.1.0` verzió kizárólag megfigyel:

- lekéri a Home Assistant entitásainak állapotát;
- összesíti az `unavailable` és `unknown` entitásokat;
- átvizsgálja a Home Assistant hibanaplóját;
- helyben, egy Ingress felületen mutatja az eredményt;
- az érzékeny adatnak tűnő naplórészleteket megjelenítés előtt kitakarja.

## Biztonsági határok

Ez a verzió:

- nem vezérel eszközöket;
- nem hív Home Assistant szolgáltatásokat;
- nem írja és nem csatolja be a `/config` könyvtárat;
- nem küld adatot OpenAIhoz, GitHubhoz vagy más külső szolgáltatáshoz;
- nem készít automatikus javítást vagy pull requestet.

Az AI- és Codex-kapcsolat csak egy későbbi verzióban kerül hozzáadásra, külön
engedélyezhető, kézi jóváhagyási kapu mögött.

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

Az alkalmazás jelenleg kísérleti állapotú.
