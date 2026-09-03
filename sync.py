"""
sync.py
--------
1. Pobiera statystyki Twoich filmów z TikToka i aktualizuje bazę Notion
   "Content Calendar" (dopasowanie po polu "Post URL").
2. Filmy, których nie ma jeszcze w Notion, zostają dodane automatycznie
   jako nowe wiersze (Status: Opublikowane).
3. Pobiera aktualną liczbę obserwujących i dopisuje ją do bazy
   "Obserwujący TikTok" (buduje historię w czasie).

Ten skrypt NIE jest uruchamiany ręcznie na co dzień — będzie go
automatycznie wywoływał GitHub Actions co 3 dni.
"""

import os
import sys
import datetime
import requests

CLIENT_KEY = os.environ["TIKTOK_CLIENT_KEY"]
CLIENT_SECRET = os.environ["TIKTOK_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["TIKTOK_REFRESH_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
NOTION_FOLLOWERS_DATABASE_ID = os.environ.get("NOTION_FOLLOWERS_DATABASE_ID")

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

    return result["access_token"]


def get_video_stats(access_token):
    """Pobiera listę filmów wraz ze statystykami."""
    url = (
        "https://open.tiktokapis.com/v2/video/list/"
        "?fields=id,title,view_count,like_count,comment_count,share_count,share_url,create_time"
    )
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


def get_follower_count(access_token):
    """Pobiera aktualną liczbę obserwujących. Wymaga scope 'user.info.stats'."""
    url = "https://open.tiktokapis.com/v2/user/info/?fields=follower_count"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", {}).get("user", {}).get("follower_count")


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
            "url": {"starts_with": post_url},
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


def create_notion_page(title, post_url, publish_date, views, likes, comments, shares):
    """Tworzy nowy wiersz w Content Calendar dla filmu, którego tam jeszcze nie było."""
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": {
            "Content name": {"title": [{"text": {"content": title or "Bez tytułu"}}]},
            "Status": {"status": {"name": "Opublikowane"}},
            "Data publikacji": {"date": {"start": publish_date}},
            "Post URL": {"url": post_url},
            "Wyświetlenia": {"number": views},
            "Polubienia": {"number": likes},
            "Komentarze": {"number": comments},
            "Udostępnienia": {"number": shares},
        },
    }
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()


def log_followers(count):
    """Dopisuje dzisiejszą liczbę obserwujących do bazy Obserwujący TikTok."""
    if not NOTION_FOLLOWERS_DATABASE_ID or count is None:
        return
    today = datetime.date.today().isoformat()
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "parent": {"database_id": NOTION_FOLLOWERS_DATABASE_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": today}}]},
            "Data": {"date": {"start": today}},
            "Liczba obserwujących": {"number": count},
        },
    }
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    print(f"Zapisano liczbę obserwujących ({count}) na dzień {today}.")


NOTION_SUMMARY_PAGE_ID = os.environ.get("NOTION_SUMMARY_PAGE_ID")


def query_all(database_id, sorts=None):
    """Pobiera WSZYSTKIE strony z bazy Notion (z paginacją)."""
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    results = []
    payload = {}
    if sorts:
        payload["sorts"] = sorts

    while True:
        resp = requests.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]

    return results


def _get_number(props, name):
    val = props.get(name, {})
    if val.get("type") == "formula":
        return val.get("formula", {}).get("number") or 0
    return val.get("number") or 0


def _get_title(props, name):
    items = props.get(name, {}).get("title", [])
    return "".join(i.get("plain_text", "") for i in items) or "Bez tytułu"


def _get_date(props, name):
    d = props.get(name, {}).get("date")
    return d.get("start") if d else None


def _get_url(props, name):
    return props.get(name, {}).get("url")


def compute_video_stats(pages):
    total_views = total_likes = total_comments = total_shares = 0
    engagements = []
    videos = []

    today = datetime.date.today()
    month_start = today.replace(day=1)
    month_views = month_likes = 0
    month_engagements = []

    for page in pages:
        props = page.get("properties", {})
        views = _get_number(props, "Wyświetlenia")
        likes = _get_number(props, "Polubienia")
        comments = _get_number(props, "Komentarze")
        shares = _get_number(props, "Udostępnienia")
        engagement = _get_number(props, "Zaangażowanie %")
        title = _get_title(props, "Content name")
        pub_date_str = _get_date(props, "Data publikacji")

        total_views += views
        total_likes += likes
        total_comments += comments
        total_shares += shares
        if views:
            engagements.append(engagement)

        videos.append({"title": title, "views": views})

        if pub_date_str:
            try:
                pub_date = datetime.date.fromisoformat(pub_date_str[:10])
            except ValueError:
                pub_date = None
            if pub_date and pub_date >= month_start:
                month_views += views
                month_likes += likes
                if views:
                    month_engagements.append(engagement)

    top3 = sorted(videos, key=lambda v: v["views"], reverse=True)[:3]
    avg_engagement = round(sum(engagements) / len(engagements), 2) if engagements else 0
    month_avg_engagement = round(sum(month_engagements) / len(month_engagements), 2) if month_engagements else 0

    return {
        "total_views": total_views,
        "total_likes": total_likes,
        "avg_engagement": avg_engagement,
        "top3": top3,
        "month_views": month_views,
        "month_likes": month_likes,
        "month_avg_engagement": month_avg_engagement,
    }


def compute_follower_growth(follower_pages):
    if not follower_pages:
        return None, None

    entries = []
    for page in follower_pages:
        props = page.get("properties", {})
        count = _get_number(props, "Liczba obserwujących")
        date_str = _get_date(props, "Data")
        if date_str:
            entries.append((datetime.date.fromisoformat(date_str[:10]), count))

    if not entries:
        return None, None

    entries.sort(key=lambda e: e[0])
    latest_date, latest_count = entries[-1]
    month_start = latest_date.replace(day=1)

    baseline = None
    for d, c in entries:
        if d < month_start:
            baseline = c
        else:
            break
    if baseline is None:
        baseline = entries[0][1]

    return latest_count, latest_count - baseline


def clear_page_content(page_id):
    """Usuwa (archiwizuje) wszystkie istniejące bloki na stronie."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    blocks = resp.json().get("results", [])

    for block in blocks:
        del_url = f"https://api.notion.com/v1/blocks/{block['id']}"
        requests.patch(del_url, json={"archived": True}, headers=headers)


def heading(text):
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": text}}]}}


def bullet(text):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"text": {"content": text}}]},
    }


def callout(text, emoji="📌"):
    return {
        "object": "block",
        "type": "callout",
        "callout": {"rich_text": [{"text": {"content": text}}], "icon": {"emoji": emoji}},
    }


def divider():
    return {"object": "block", "type": "divider", "divider": {}}


def write_summary(video_stats, follower_count, follower_growth):
    if not NOTION_SUMMARY_PAGE_ID:
        return

    now_str = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    blocks = [
        callout(f"Ostatnia aktualizacja: {now_str}", emoji="🕒"),
        heading("📊 Statystyki ogólne (wszystkie filmy)"),
        bullet(f"Łączne wyświetlenia: {video_stats['total_views']:,}".replace(",", " ")),
        bullet(f"Łączne polubienia: {video_stats['total_likes']:,}".replace(",", " ")),
        bullet(f"Średnie zaangażowanie: {video_stats['avg_engagement']}%"),
        divider(),
        heading("🏆 TOP 3 filmy"),
    ]

    medals = ["🥇", "🥈", "🥉"]
    for i, v in enumerate(video_stats["top3"]):
        blocks.append(bullet(f"{medals[i]} {v['title']} — {v['views']:,} wyświetleń".replace(",", " ")))

    month_name = datetime.date.today().strftime("%B %Y")
    blocks += [
        divider(),
        heading(f"📅 Ten miesiąc ({month_name})"),
        bullet(f"Wyświetlenia w tym miesiącu: {video_stats['month_views']:,}".replace(",", " ")),
        bullet(f"Polubienia w tym miesiącu: {video_stats['month_likes']:,}".replace(",", " ")),
        bullet(f"Średnie zaangażowanie w tym miesiącu: {video_stats['month_avg_engagement']}%"),
    ]

    if follower_count is not None:
        sign = "+" if (follower_growth or 0) >= 0 else ""
        blocks.append(bullet(f"Obserwujący: {follower_count} (przyrost w tym miesiącu: {sign}{follower_growth})"))

    clear_page_content(NOTION_SUMMARY_PAGE_ID)

    url = f"https://api.notion.com/v1/blocks/{NOTION_SUMMARY_PAGE_ID}/children"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    resp = requests.patch(url, json={"children": blocks}, headers=headers)
    resp.raise_for_status()
    print("Zaktualizowano stronę Podsumowanie.")


def main():
    print("Pobieram token dostępu...")
    access_token = get_access_token()

    print("Pobieram listę filmów z TikToka...")
    videos = get_video_stats(access_token)
    print(f"Znaleziono {len(videos)} filmów.")

    updated = 0
    created = 0

    for video in videos:
        raw_url = video.get("share_url")
        if not raw_url:
            continue

        post_url = raw_url.split("?")[0]
        views = video.get("view_count", 0)
        likes = video.get("like_count", 0)
        comments = video.get("comment_count", 0)
        shares = video.get("share_count", 0)

        page_id = find_notion_page(post_url)

        if page_id:
            update_notion_page(page_id, views, likes, comments, shares)
            print(f"Zaktualizowano: {post_url}")
            updated += 1
        else:
            create_time = video.get("create_time")
            publish_date = (
                datetime.datetime.fromtimestamp(create_time, datetime.timezone.utc).date().isoformat()
                if create_time
                else datetime.date.today().isoformat()
            )
            create_notion_page(
                title=video.get("title"),
                post_url=post_url,
                publish_date=publish_date,
                views=views,
                likes=likes,
                comments=comments,
                shares=shares,
            )
            print(f"Dodano nowy wiersz: {post_url}")
            created += 1

    print(f"\nFilmy — zaktualizowano: {updated}, dodano nowych: {created}.")

    # Obserwujący (opcjonalne — działa dopiero po dodaniu scope 'user.info.stats')
    try:
        follower_count = get_follower_count(access_token)
        if follower_count is not None:
            log_followers(follower_count)
        else:
            print("Brak danych o liczbie obserwujących (sprawdź scope 'user.info.stats').")
    except requests.HTTPError as e:
        print(f"Nie udało się pobrać liczby obserwujących: {e.response.status_code} — {e.response.text}")

    # Podsumowanie / dashboard
    try:
        print("\nGeneruję podsumowanie...")
        all_pages = query_all(NOTION_DATABASE_ID)
        video_stats = compute_video_stats(all_pages)

        follower_count = follower_growth = None
        if NOTION_FOLLOWERS_DATABASE_ID:
            follower_pages = query_all(NOTION_FOLLOWERS_DATABASE_ID)
            follower_count, follower_growth = compute_follower_growth(follower_pages)

        write_summary(video_stats, follower_count, follower_growth)
    except requests.HTTPError as e:
        print(f"Nie udało się zaktualizować podsumowania: {e.response.status_code} — {e.response.text}")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        print(f"Błąd API: {e.response.status_code} — {e.response.text}")
        sys.exit(1)
