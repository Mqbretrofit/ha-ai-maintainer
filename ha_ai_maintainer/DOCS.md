# HA AI Maintainer

Az alkalmazás a Home Assistant saját, belső REST- és WebSocket API-proxyján
keresztül, kizárólag olvasási műveletekkel készít
rendszerállapot-összesítést.

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

## Hálózat és adatkezelés

Az alkalmazás nem nyit hostportot, csak a Home Assistant Ingress felületén
érhető el. Nem küld adatot külső szolgáltatásnak, és nem használ OpenAI- vagy
GitHub-kulcsot.

A `0.1.1` verzió a strukturált `system_log/list` WebSocket parancsot használja.
Ehhez nem kér új Home Assistant- vagy Supervisor-jogosultságot. Ha a napló nem
érhető el, az entitásvizsgálat eredménye továbbra is megjelenik.

A `0.1.2` verzió külön kezeli az egyedi naplóbejegyzések számát és azok összes
ismétlődését. A problémás entitásokat domain, a naplóbejegyzéseket forrás szerint
is összesíti. Entitást automatikusan nem hagy figyelmen kívül.

## Hibaelhárítás

Ha a felület nem tölt be:

1. Nyisd meg az alkalmazás naplóját.
2. Ellenőrizd, hogy a Home Assistant teljesen elindult-e.
3. Indítsd újra a HA AI Maintainer alkalmazást.
