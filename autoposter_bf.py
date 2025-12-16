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

REPOST_LOG_FILE = "reposted_feed.txt"


# --------------------------------------------------
# Helpers
# --------------------------------------------------
def log(msg: str) -> None:
    now = datetime.now(timezone.utc).strftime("[%H:%M:%S]")
    print(f"{now} {msg}")


def parse_time(record, post):
    for attr in ["createdAt", "indexedAt", "created_at"]:
        val = getattr(record, attr, None) or getattr(post, attr, None)
        if val:
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except Exception:
                pass
    return None


def has_media(post) -> bool:
    embed = getattr(post, "embed", None)
    if not embed:
        return False

    # images
    images = getattr(embed, "images", None)
    if isinstance(images, list) and images:
        return True

    # video / media
    media = getattr(embed, "media", None)
    if media:
        imgs = getattr(media, "images", None)
        if isinstance(imgs, list) and imgs:
            return True

    # external link met thumbnail
    external = getattr(embed, "external", None)
    if external and getattr(external, "thumb", None):
        return True

    return False


def is_quote_post(post) -> bool:
    embed = getattr(post, "embed", None)
    if not embed:
        return False
    return getattr(embed, "record", None) is not None


# --------------------------------------------------
# Main
# --------------------------------------------------
def main():
    username = os.getenv("BSKY_USERNAME_BF")
    password = os.getenv("BSKY_PASSWORD_BF")

    if not username or not password:
        log("❌ Geen credentials gevonden.")
        return

    client = Client()
    client.login(username, password)
    log("✅ Ingelogd.")

    # Feed ophalen
    try:
        log("📥 Feed ophalen...")
        feed = client.app.bsky.feed.get_feed(
            {"feed": FEED_URI, "limit": 100}
        )
        items = feed.feed or []
        log(f"📊 {len(items)} posts gevonden.")
    except Exception as e:
        log(f"⚠️ Feed fout: {e}")
        return

    # Repost-log laden
    done = set()
    if os.path.exists(REPOST_LOG_FILE):
        with open(REPOST_LOG_FILE, "r", encoding="utf-8") as f:
            done = {line.strip() for line in f if line.strip()}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    candidates = []

    for item in items:
        post = item.post
        record = post.record
        uri = post.uri
        cid = post.cid
        handle = getattr(post.author, "handle", "unknown")

        # ❌ reposts, replies
        if getattr(item, "reason", None) is not None:
            continue
        if getattr(record, "reply", None):
            continue

        # ❌ quote-posts
        if is_quote_post(post):
            continue

        # ❌ tekst-only
        if not has_media(post):
            continue

        # ❌ al gedaan
        if uri in done:
            continue

        created = parse_time(record, post)
        if not created or created < cutoff:
            continue

        candidates.append(
            {
                "handle": handle,
                "uri": uri,
                "cid": cid,
                "created": created,
            }
        )

    log(f"🧩 {len(candidates)} geldige media-posts.")

    if not candidates:
        log("🔥 Klaar — niets te doen.")
        return

    # Oud → nieuw
    candidates.sort(key=lambda x: x["created"])

    per_user = {}
    reposted = 0
    liked = 0

    for post in candidates:
        if reposted >= MAX_PER_RUN:
            break

        handle = post["handle"]
        per_user.setdefault(handle, 0)

        if per_user[handle] >= MAX_PER_USER:
            continue

        uri = post["uri"]
        cid = post["cid"]

        # Repost
        try:
            client.app.bsky.feed.repost.create(
                repo=client.me.did,
                record={
                    "subject": {"uri": uri, "cid": cid},
                    "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            )
            reposted += 1
            per_user[handle] += 1
            done.add(uri)
            log(f"🔁 Gerepost @{handle}")
        except Exception as e:
            log(f"⚠️ Repost fout @{handle}: {e}")
            continue

        # Like
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
            log(f"⚠️ Like fout @{handle}: {e}")

        time.sleep(DELAY_SECONDS)

    # Log opslaan
    with open(REPOST_LOG_FILE, "w", encoding="utf-8") as f:
        for uri in done:
            f.write(uri + "\n")

    log(f"🔥 Klaar — {reposted} reposts ({liked} likes)")
    log(f"⏰ Einde run {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")


if __name__ == "__main__":
    main()