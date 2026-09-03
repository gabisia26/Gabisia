# Ten plik trzeba wgrać do repozytorium GitHub pod ścieżką:
# .github/workflows/sync.yml
#
# Uruchamia sync.py automatycznie co 3 dni.

name: Sync TikTok stats to Notion

on:
  schedule:
    # Uruchomienie co 3 dni o 6:00 UTC (8:00 czasu polskiego)
    - cron: "0 6 */3 * *"
  workflow_dispatch: # pozwala też uruchomić ręcznie z zakładki "Actions"

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - name: Pobierz kod repozytorium
        uses: actions/checkout@v4

      - name: Ustaw Pythona
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Zainstaluj zależności
        run: pip install -r requirements.txt

      - name: Uruchom synchronizację
        env:
          TIKTOK_CLIENT_KEY: ${{ secrets.TIKTOK_CLIENT_KEY }}
          TIKTOK_CLIENT_SECRET: ${{ secrets.TIKTOK_CLIENT_SECRET }}
          TIKTOK_REFRESH_TOKEN: ${{ secrets.TIKTOK_REFRESH_TOKEN }}
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
        run: python sync.py
