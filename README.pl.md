# Emby Plus

[English](README.md)

Odtwarzacze Emby w Home Assistant konfigurowane w panelu, które same wracają, gdy wraca
serwer Emby. Zastępuje wbudowaną
[integrację Emby](https://www.home-assistant.io/integrations/emby) i przejmuje jej encje.

## Dlaczego

Wbudowana integracja działa dobrze, dopóki serwer Emby jest stale włączony. Zawodzi, gdy
serwer włącza się i wyłącza, np. NAS z harmonogramem zasilania:

| Problem wbudowanej integracji `emby` | Emby Plus |
| --- | --- |
| Tylko YAML: *„Ta integracja nie została skonfigurowana w interfejsie użytkownika”*. | Konfiguracja w **Ustawienia → Urządzenia i usługi**, tam też zmiana adresu i klucza API. |
| [pyEmby](https://github.com/mezz64/pyEmby) rejestruje się na serwerze **raz**, przy starcie HA. Jeśli serwer jest wtedy wyłączony, wszystkie `media_player.emby_*` są niedostępne aż do następnego restartu HA. Nie ma akcji przeładowania. | Gdy serwer nie odpowiada, start zgłasza `ConfigEntryNotReady` i HA sam ponawia go w tle z rosnącym odstępem. Websocket, który zerwie się później, łączy się ponownie po 5, 10, 30, a potem co 60 s. Utrata połączenia trafia do dziennika raz, a nie co kilka sekund. |
| Adres plakatu nie ma prefiksu `/emby` i prosi o obraz *Thumb*, którego pozycje zwykle nie mają. Proxy obrazów HA dostaje 404, więc `entity_picture` jest puste. | Obraz *Primary* pozycji, a gdy go brak, serialu albo albumu, pod `/emby/Items/{id}/Images/Primary`. Działa przez proxy HA, także poza siecią domową. |
| Nie ma urządzenia serwera ani informacji, czy serwer działa. | Urządzenie **serwera Emby** z czujnikiem łączności *Serwer* i czujnikiem *Aktywne odtwarzania*. Jego atrybut `playing` pokazuje, co gra i gdzie. |
| pyEmby otwiera własną sesję aiohttp i używa przestarzałych API asyncio. | Mały klient na wspólnej sesji HA, bez dodatkowych zależności. |
| Podczas odtwarzania stan zapisuje się co 1,5 s, tylko dlatego, że zmieniła się pozycja. | Pozycja zapisuje się tylko przy przewinięciu albo pauzie, a w międzyczasie HA wylicza ją sam. |

## Instalacja

HACS: dodaj to repozytorium jako własne (kategoria *Integracja*) i zainstaluj **Emby Plus**.

Ręcznie: skopiuj `custom_components/emby_plus` do `/config/custom_components/`. Przy
zamontowanym udziale Samba możesz zamiast tego użyć `scripts/deploy.sh`. Zrestartuj HA.

## Konfiguracja

1. Utwórz klucz API w panelu Emby: **Zaawansowane → Klucze API**.
2. **Ustawienia → Urządzenia i usługi → Dodaj integrację → Emby Plus**. Wpisz host, port
   (8096, a z HTTPS 8920) i klucz API. Jeśli w `configuration.yaml` jest jeszcze blok
   `platform: emby`, formularz wypełni się z niego.

## Przejście z wbudowanej integracji

Obie integracje nazywają odtwarzacz `<DeviceId>.<Client>` (`unique_id`), więc Emby Plus może
przejąć istniejące encje:

1. Dodaj Emby Plus jak wyżej. Dopóki w `configuration.yaml` jest
   `media_player: - platform: emby`, w **Ustawienia → Naprawy** pojawia się prośba o jego
   usunięcie. Do tego czasu obie integracje pokazywałyby te same odtwarzacze, więc Emby
   Plus nie rusza jeszcze encji wbudowanej integracji.
2. Usuń ten blok i zrestartuj HA.
3. Przy starcie Emby Plus przenosi do siebie każdą encję `media_player` wbudowanej
   integracji `emby`. Każda zachowuje **identyfikator encji**, nazwę, ikonę, obszar,
   aliasy, etykiety oraz ukrycie albo wyłączenie. Dashboardy i automatyzacje działają
   dalej.

## Encje

- `media_player.*`: jedna na aplikację Emby na urządzeniu, np. *Emby for LG* na
  telewizorze.
  - Stany: odtwarzanie, pauza albo bezczynny. Odtwarzacz jest niedostępny, gdy aplikacja
    jest zamknięta albo serwer wyłączony.
  - Atrybuty: tytuł, serial, sezon i odcinek, album i wykonawca, czas trwania, pozycja,
    plakat.
  - Sterowanie: play, pauza, stop, następny, poprzedni i przewijanie, w aplikacjach, które
    na to pozwalają.
  - `app_name` to użytkownik Emby, tak jak we wbudowanej integracji.
- `binary_sensor.<serwer>_server`: połączenie z serwerem.
- `sensor.<serwer>_active_playbacks`: liczba sesji, które odtwarzają albo są na pauzie.
  Atrybut `playing` podaje dla każdej `device`, `client` i `title`.

## Rozwój

```sh
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Testy działają na HA 2026.10 (`pytest-homeassistant-custom-component`) i nie potrzebują
serwera Emby. Dane sesji w `tests/fixtures/` są syntetyczne.

## Licencja

Apache 2.0. Emby jest znakiem towarowym Emby LLC. Projekt nie jest związany z Emby.
