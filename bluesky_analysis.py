import csv
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


# ==========================================
# INSTELLINGEN
# ==========================================

ACCOUNTS = [
    "pinupstickers.bsky.social",
    "leonie04.bsky.social",
    "eyescandy.bsky.social",
    "sexypinups.bsky.social",
    "dmphotos.bsky.social",
    "blackandwhites.bsky.social",
    "sandrasia.bsky.social",
    "jey09.bsky.social",
    "tasha510.bsky.social",
]

POSTS_PER_ACCOUNT = 500

TIMEZONE = "Europe/Amsterdam"

API_BASES = [
    "https://public.api.bsky.app/xrpc",
    "https://bsky.social/xrpc",
]

TIMEOUT = 30
MAX_RETRIES = 3

OUTPUT = Path("analysis_output")
OUTPUT.mkdir(exist_ok=True)

session = requests.Session()

session.headers.update({
    "User-Agent": "BlueskyTimeAnalyzer/1.0"
})


# ==========================================
# HULPFUNCTIES
# ==========================================

def number(value):
    try:
        return int(value or 0)
    except:
        return 0


def parse_date(value):

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    return datetime.fromisoformat(value)


def api_request(params):

    last_error = None

    for base in API_BASES:

        url = base + "/app.bsky.feed.getAuthorFeed"

        for attempt in range(MAX_RETRIES):

            try:

                response = session.get(
                    url,
                    params=params,
                    timeout=TIMEOUT
                )

                response.raise_for_status()

                return response.json()

            except requests.RequestException as error:

                last_error = error

                print(
                    f"API fout ({base}) "
                    f"poging {attempt + 1}/{MAX_RETRIES}"
                )

                time.sleep(3)

    raise last_error


# ==========================================
# POSTS OPHALEN
# ==========================================

def get_posts(account):

    print()
    print("=" * 50)
    print(account)
    print("=" * 50)

    posts = []

    cursor = None

    seen = set()

    while len(posts) < POSTS_PER_ACCOUNT:

        params = {
            "actor": account,
            "limit": 100,
            "filter": "posts_no_replies"
        }

        if cursor:
            params["cursor"] = cursor

        try:

            data = api_request(params)

        except Exception as error:

            print("Account gestopt wegens API fout:")
            print(error)

            break

        feed = data.get("feed", [])

        if not feed:
            break

        for item in feed:

            if len(posts) >= POSTS_PER_ACCOUNT:
                break

            # Reposts overslaan

            reason = item.get("reason")

            if reason:

                if (
                    reason.get("$type")
                    ==
                    "app.bsky.feed.defs#reasonRepost"
                ):

                    continue

            post = item.get("post", {})

            if not post:
                continue

            # Replies overslaan

            if post.get("reply"):
                continue

            uri = post.get("uri")

            if not uri:
                continue

            if uri in seen:
                continue

            record = post.get("record", {})

            created = (
                record.get("createdAt")
                or post.get("indexedAt")
            )

            if not created:
                continue

            seen.add(uri)

            posts.append({

                "account": account,

                "uri": uri,

                "created_at_utc": created,

                "likes":
                    number(post.get("likeCount")),

                "reposts":
                    number(post.get("repostCount")),

                "replies":
                    number(post.get("replyCount")),

                "quotes":
                    number(post.get("quoteCount"))
            })

        cursor = data.get("cursor")

        print(
            f"Opgehaald: "
            f"{len(posts)}/{POSTS_PER_ACCOUNT}"
        )

        if not cursor:
            break

        time.sleep(0.5)

    return posts


# ==========================================
# NEDERLANDSE TIJD TOEVOEGEN
# ==========================================

def add_local_time(posts):

    timezone = ZoneInfo(TIMEZONE)

    weekdays = [

        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday"
    ]

    for post in posts:

        dt = parse_date(
            post["created_at_utc"]
        )

        local = dt.astimezone(timezone)

        post["local_time"] = (
            local.isoformat()
        )

        post["weekday"] = (
            weekdays[local.weekday()]
        )

        post["hour"] = local.hour

        post["engagement"] = (

            post["likes"]

            + post["reposts"]

            + post["replies"]

            + post["quotes"]
        )


# ==========================================
# CSV OPSLAAN
# ==========================================

def save_csv(filename, rows):

    if not rows:
        return

    path = OUTPUT / filename

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=rows[0].keys()
        )

        writer.writeheader()

        writer.writerows(rows)


# ==========================================
# ANALYSE PER UUR
# ==========================================

def analyse_hours(posts):

    groups = defaultdict(list)

    for post in posts:

        groups[
            (
                post["account"],
                post["hour"]
            )
        ].append(post)

    results = []

    for (
        account,
        hour
    ), group in groups.items():

        likes = [
            x["likes"]
            for x in group
        ]

        reposts = [
            x["reposts"]
            for x in group
        ]

        engagement = [
            x["engagement"]
            for x in group
        ]

        results.append({

            "account": account,

            "hour": hour,

            "posts": len(group),

            "average_likes":
                round(
                    statistics.mean(likes),
                    2
                ),

            "median_likes":
                statistics.median(likes),

            "average_reposts":
                round(
                    statistics.mean(reposts),
                    2
                ),

            "median_reposts":
                statistics.median(reposts),

            "average_engagement":
                round(
                    statistics.mean(
                        engagement
                    ),
                    2
                ),

            "median_engagement":
                statistics.median(
                    engagement
                )
        })

    return results


# ==========================================
# PROGRAMMA
# ==========================================

def main():

    print()
    print(
        "BLUESKY POSTING TIME ANALYSIS"
    )

    print(
        f"Accounts: {len(ACCOUNTS)}"
    )

    print(
        f"Posts per account: "
        f"{POSTS_PER_ACCOUNT}"
    )

    all_posts = []

    for account in ACCOUNTS:

        posts = get_posts(account)

        all_posts.extend(posts)

    if not all_posts:

        print("Geen posts gevonden.")

        return

    add_local_time(all_posts)

    save_csv(
        "bluesky_posts.csv",
        all_posts
    )

    hour_results = analyse_hours(
        all_posts
    )

    save_csv(
        "bluesky_hour_summary.csv",
        hour_results
    )

    print()
    print("============================")
    print("KLAAR")
    print("============================")

    print(
        f"Totaal posts: "
        f"{len(all_posts)}"
    )

    print()
    print(
        "Bestanden staan in:"
    )

    print(
        "analysis_output/"
    )


if __name__ == "__main__":
    main()