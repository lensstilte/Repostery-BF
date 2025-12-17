from atproto import Client
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# === CONFIG ===
FEED_URI = "at://did:plc:jaka644beit3x4vmmg6yysw7/app.bsky.feed.generator/aaamyqwuiyasw"
MAX_PER_RUN = 100
MAX_PER_USER = 5
HOURS_BACK = 3
DELAY_SECONDS = 1
REPOST_LOG_FILE = "reposted_hb.txt"


def log(msg: str) -> None:
    now = datetime.now(timezone.utc).strftime("[%H:%M:%S]")
    print(f"{now} {msg}")


def load_done(path: str) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    with p.open("r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def append_done(path: str, uri: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(uri + "\n")


def parse_time(record, post):
    for attr in ("createdAt", "indexedAt", "created_at", "timestamp"):
        val = getattr(record, attr, None) or getattr(post, attr, None)
        if not val:
            continue
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            continue
    return None


def is_quote_post(record) -> bool:
    """Blokkeer quotes (record embeds)."""
    embed = getattr(record, "embed", None)
    if not embed:
        return False
    return bool(getattr(embed, "record", None) or getattr(embed, "recordWithMedia", None))


def has_media(record) -> bool:
    """
    Alleen echte media (images/video). Geen external/link cards,
    zodat text/link posts nooit worden meegenomen.
    """
    embed = getattr(record, "embed", None)
    if not embed:
        return False

    # images direct
    images = getattr(embed, "images", None)
    if isinstance(images, list) and images:
        return True

    # video direct
    if getattr(embed, "video", None):
        return True

    # media wrapper variants
    media = getattr(embed, "media", None)
    if media:
        imgs = getattr(media, "images", None)
        if isinstance(imgs, list) and imgs:
            return True
        if getattr(media, "video", None):
            return True

    return False


def main():
    username = os.getenv("BSKY_USERNAME_HB")
    password = os.getenv("BSKY_PASSWORD_HB")

    if not username or not password:
        log("❌ Geen BSKY_USERNAME_HB / BSKY_PASSWORD_HB gevonden in env.")
        return

    client = Client()
    client.login(username, password)
    log("✅ Ingelogd.")

    # Feed ophalen
    try:
        log("📥 Feed ophalen...")
        feed = client.app.bsky.feed.get_feed({"feed": FEED_URI, "limit": 100})
        items = feed.feed or []
        log(f"📊 {len(items)} posts gevonden in feed.")
    except Exception as e:
        log(f"⚠️ Fout bij ophalen feed: {e}")
        return

    done = load_done(REPOST_LOG_FILE)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)

    candidates = []

    # Oudste eerst (API is vaak newest-first)
    for item in reversed(items):
        post = item.post
        record = post.record
        uri = post.uri
        cid = post.cid
        handle = getattr(post.author, "handle", "onbekend")

        # ❌ reposts/boosts
        if getattr(item, "reason", None) is not None:
            continue

        # ❌ replies
        if getattr(record, "reply", None):
            continue

        # ❌ quotes
        if is_quote_post(record):
            continue

        # ❌ text/link-only
        if not has_media(record):
            continue

        # ❌ al gedaan
        if uri in done:
            continue

        created_dt = parse_time(record, post)
        if not created_dt or created_dt < cutoff:
            continue

        candidates.append(
            {"handle": handle, "uri": uri, "cid": cid, "created": created_dt}
        )

    log(f"🧩 {len(candidates)} geschikte media-posts gevonden.")

    if not candidates:
        log("🔥 Klaar — 0 reposts uitgevoerd (0 geliked).")
        log(f"⏰ Run afgerond op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        return

    # Oud → nieuw
    candidates.sort(key=lambda x: x["created"])

    per_user_count: dict[str, int] = {}
    reposted = 0
    liked = 0

    for p in candidates:
        if reposted >= MAX_PER_RUN:
            break

        handle = p["handle"]
        per_user_count.setdefault(handle, 0)
        if per_user_count[handle] >= MAX_PER_USER:
            continue

        uri = p["uri"]
        cid = p["cid"]

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
            per_user_count[handle] += 1
            done.add(uri)
            append_done(REPOST_LOG_FILE, uri)
            log(f"🔁 Gerepost @{handle}")
        except Exception as e:
            log(f"⚠️ Fout bij repost @{handle}: {e}")
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
            log(f"⚠️ Fout bij liken @{handle}: {e}")

        time.sleep(DELAY_SECONDS)

    log(f"🔥 Klaar — {reposted} reposts uitgevoerd ({liked} geliked).")
    log(f"ℹ️ Per-user limiet: {MAX_PER_USER}, tijdvenster: laatste {HOURS_BACK} uur, max {MAX_PER_RUN} per run.")
    log(f"⏰ Run afgerond op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")


if __name__ == "__main__":
    main()