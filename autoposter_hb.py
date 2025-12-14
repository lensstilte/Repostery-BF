from atproto import Client
import os
import time
from datetime import datetime, timedelta, timezone

# === CONFIG ===
FEED_URI = "at://did:plc:jaka644beit3x4vmmg6yysw7/app.bsky.feed.generator/aaamyqwuiyasw"
MAX_PER_RUN = 100
MAX_PER_USER = 5
HOURS_BACK = 3
DELAY_SECONDS = 0
REPOST_LOG_FILE = "reposted_hb.txt"


def log(msg: str) -> None:
    now = datetime.now(timezone.utc).strftime("[%H:%M:%S]")
    print(f"{now} {msg}")


def parse_time(record, post):
    for attr in ["createdAt", "indexedAt", "created_at", "timestamp"]:
        val = getattr(record, attr, None) or getattr(post, attr, None)
        if val:
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except Exception:
                continue
    return None


def main():
    username = os.getenv("BSKY_USERNAME_HB")
    password = os.getenv("BSKY_PASSWORD_HB")

    if not username or not password:
        log("❌ Geen BSKY_USERNAME_HB / BSKY_PASSWORD_HB gevonden in env.")
        return

    client = Client()
    client.login(username, password)
    log("✅ Ingelogd.")

    try:
        log("📥 Feed ophalen...")
        feed = client.app.bsky.feed.get_feed({"feed": FEED_URI, "limit": 100})
        items = feed.feed
        log(f"📊 {len(items)} posts gevonden in feed.")
    except Exception as e:
        log(f"⚠️ Fout bij ophalen feed: {e}")
        return

    done = set()
    if os.path.exists(REPOST_LOG_FILE):
        with open(REPOST_LOG_FILE, "r", encoding="utf-8") as f:
            done = set(line.strip() for line in f if line.strip())

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    candidates = []

    for item in items:
        post = item.post
        record = post.record
        uri = post.uri
        cid = post.cid
        handle = getattr(post.author, "handle", "onbekend")

        if getattr(item, "reason", None) is not None:
            continue
        if getattr(record, "reply", None):
            continue
        if uri in done:
            continue

        created_dt = parse_time(record, post)
        if not created_dt or created_dt < cutoff:
            continue

        candidates.append(
            {
                "handle": handle,
                "uri": uri,
                "cid": cid,
                "created": created_dt,
            }
        )

    log(f"🧩 {len(candidates)} geschikte posts gevonden.")

    if not candidates:
        log("🔥 Klaar — 0 reposts uitgevoerd (0 geliked).")
        log(f"⏰ Run afgerond op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        return

    candidates.sort(key=lambda x: x["created"])

    per_user_count = {}
    reposted = 0
    liked = 0

    for post in candidates:
        if reposted >= MAX_PER_RUN:
            break

        handle = post["handle"]
        uri = post["uri"]
        cid = post["cid"]

        per_user_count[handle] = per_user_count.get(handle, 0)
        if per_user_count[handle] >= MAX_PER_USER:
            continue

        try:
            client.app.bsky.feed.repost.create(
                repo=client.me.did,
                record={
                    "subject": {"uri": uri, "cid": cid},
                    "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
            reposted += 1
            per_user_count[handle] += 1
            done.add(uri)
            log(f"🔁 Gerepost @{handle}")
        except Exception as e:
            log(f"⚠️ Fout bij repost @{handle}: {e}")
            continue

        try:
            client.app.bsky.feed.like.create(
                repo=client.me.did,
                record={
                    "subject": {"uri": uri, "cid": cid},
                    "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
            liked += 1
            log(f"❤️ Geliked @{handle}")
        except Exception as e:
            log(f"⚠️ Fout bij liken @{handle}: {e}")

        time.sleep(DELAY_SECONDS)

    with open(REPOST_LOG_FILE, "w", encoding="utf-8") as f:
        for uri in done:
            f.write(uri + "\n")

    log(f"🔥 Klaar — {reposted} reposts uitgevoerd ({liked} geliked).")
    log(
        f"ℹ️ Per-user limiet: {MAX_PER_USER}, tijdvenster: laatste {HOURS_BACK} uur, max {MAX_PER_RUN} per run."
    )
    log(f"⏰ Run afgerond op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")


if __name__ == "__main__":
    main()
