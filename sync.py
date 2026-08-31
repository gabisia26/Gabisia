"""
sync.py
--------
Pobiera statystyki Twoich filmów z TikToka i aktualizuje bazę Notion
"Content Calendar" (dopasowanie po polu "Post URL").
 
Ten skrypt NIE jest uruchamiany ręcznie na co dzień — będzie go
automatycznie wywoływał GitHub Actions co 3 dni.
 
Wszystkie potrzebne wartości (klucze, tokeny) są pobierane ze zmiennych
środowiskowych (env variables), a nie wpisane na sztywno w kodzie —
tak żeby nigdy nie trafiły przypadkiem do publicznego repozytorium.
"""
 
import os
import sys
import requests
 
CLIENT_KEY = os.environ["TIKTOK_CLIENT_KEY"]
CLIENT_SECRET = os.environ["TIKTOK_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["TIKTOK_REFRESH_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
 
NOTION_VERSION = "2022-06-28"
 
 
def get_access_token():
    """Wymienia refresh_token na świeży access_token (ważny 24h)."""
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    data = {
        "client_key": CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(url, data=data, headers=headers)
    resp.raise_for_status()
    result = resp.json()
 
    if "access_token" not in result:
        print("Odpowiedź TikToka nie zawiera access_token. Pełna odpowiedź:")
        print(result)
        raise SystemExit(1)
 
    new_refresh_token = result.get("refresh_token")
    if new_refresh_token and new_refresh_token != REFRESH_TOKEN:
        print("UWAGA: TikTok wydał nowy refresh_token.")
        print("Zaktualizuj sekret TIKTOK_REFRESH_TOKEN w GitHub na wartość:")
        print(new_refresh_token)
        # Ten print pojawi się w logach GitHub Actions, żebyś to zauważyła.
 
    return result["access_token"]
 
 
def get_video_stats(access_token):
    """Pobiera listę filmów wraz ze statystykami."""
    url = "https://open.tiktokapis.com/v2/video/list/?fields=id,title,view_count,like_count,comment_count,share_count,share_url"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    body = {"max_count": 20}
 
    resp = requests.post(url, json=body, headers=headers)
    resp.raise_for_status()
    data = resp.json()
 
    videos = data.get("data", {}).get("videos", [])
    return videos
 
 
def find_notion_page(post_url):
    """Szuka w bazie Notion strony, gdzie Post URL pasuje do podanego linku."""
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "filter": {
            "property": "Post URL",
            "url": {"equals": post_url},
        }
    }
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0]["id"] if results else None
 
 
def update_notion_page(page_id, views, likes, comments, shares):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "properties": {
            "Wyświetlenia": {"number": views},
            "Polubienia": {"number": likes},
            "Komentarze": {"number": comments},
            "Udostępnienia": {"number": shares},
        }
    }
    resp = requests.patch(url, json=payload, headers=headers)
    resp.raise_for_status()
 
 
def main():
    print("Pobieram token dostępu...")
    access_token = get_access_token()
 
    print("Pobieram listę filmów z TikToka...")
    videos = get_video_stats(access_token)
    print(f"Znaleziono {len(videos)} filmów.")
 
    updated = 0
    skipped = 0
 
    for video in videos:
        post_url = video.get("share_url")
        if not post_url:
            continue
 
        page_id = find_notion_page(post_url)
        if not page_id:
            print(f"Pominięto (brak dopasowania w Notion): {post_url}")
            skipped += 1
            continue
 
        update_notion_page(
            page_id,
            views=video.get("view_count", 0),
            likes=video.get("like_count", 0),
            comments=video.get("comment_count", 0),
            shares=video.get("share_count", 0),
        )
        print(f"Zaktualizowano: {post_url}")
        updated += 1
 
    print(f"\nGotowe. Zaktualizowano {updated} filmów, pominięto {skipped}.")
 
 
if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"Błąd API: {e.response.status_code} — {e.response.text}")
        sys.exit(1)
