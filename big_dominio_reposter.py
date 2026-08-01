import os
import time
from datetime import datetime, timezone

from atproto import Client


# ============================================================
# INSTELLINGEN
# ============================================================

BSKY_USERNAME = os.getenv("BSKY_USERNAME")
BSKY_PASSWORD = os.getenv("BSKY_PASSWORD")

TARGET_ACCOUNT = "big-dominio.bsky.social"

LATEST_NORMAL_POSTS = 10
LATEST_MEDIA_REPLIES = 0

SLEEP_SECONDS = 2
UNREPOST_WAIT_SECONDS = 1


# ============================================================
# HULPFUNCTIES
# ============================================================

def get_embed_type(embed) -> str:
    if embed is None:
        return ""

    return (
        getattr(embed, "py_type", "")
        or getattr(embed, "$type", "")
        or str(type(embed))
    ).lower()


def has_media(post) -> bool:
    """
    Alleen afbeeldingen en video's toestaan.
    """
    embed = getattr(post.record, "embed", None)
    embed_type = get_embed_type(embed)

    return (
        "images" in embed_type
        or "video" in embed_type
    )


def is_quote_post(post) -> bool:
    """
    Quote posts uitsluiten.

    Een recordWithMedia bevat zowel een quote als media en wordt
    daarom eveneens uitgesloten.
    """
    embed = getattr(post.record, "embed", None)
    embed_type = get_embed_type(embed)

    return "record" in embed_type


def is_reply(post) -> bool:
    return getattr(post.record, "reply", None) is not None


def get_post_datetime(post) -> datetime:
    """
    Datum gebruiken om de gecombineerde selectie oud -> nieuw
    te sorteren.
    """
    value = (
        getattr(post, "indexed_at", None)
        or getattr(post.record, "created_at", None)
    )

    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


# ============================================================
# POSTS OPHALEN
# ============================================================

def get_target_posts(client: Client):
    target_profile = client.app.bsky.actor.get_profile({
        "actor": TARGET_ACCOUNT
    })
    target_did = target_profile.did

    normal_posts = []
    media_replies = []

    cursor = None

    while (
        len(normal_posts) < LATEST_NORMAL_POSTS
        or len(media_replies) < LATEST_MEDIA_REPLIES
    ):
        params = {
            "actor": target_did,
            "limit": 100,
        }

        if cursor:
            params["cursor"] = cursor

        response = client.app.bsky.feed.get_author_feed(params)

        if not response.feed:
            break

        for item in response.feed:
            # Repost-activiteiten in de author feed overslaan
            if getattr(item, "reason", None) is not None:
                continue

            post = item.post

            # Alleen content die door het target-account zelf is gemaakt
            if post.author.did != target_did:
                continue

            # Alleen afbeeldingen of video's
            if not has_media(post):
                continue

            # Geen quote posts of quote-met-media
            if is_quote_post(post):
                continue

            if is_reply(post):
                if len(media_replies) < LATEST_MEDIA_REPLIES:
                    media_replies.append(post)
                    print(
                        f"Media reply geselecteerd "
                        f"({len(media_replies)}/{LATEST_MEDIA_REPLIES}): "
                        f"{post.uri}"
                    )
            else:
                if len(normal_posts) < LATEST_NORMAL_POSTS:
                    normal_posts.append(post)
                    print(
                        f"Gewone mediapost geselecteerd "
                        f"({len(normal_posts)}/{LATEST_NORMAL_POSTS}): "
                        f"{post.uri}"
                    )

            if (
                len(normal_posts) >= LATEST_NORMAL_POSTS
                and len(media_replies) >= LATEST_MEDIA_REPLIES
            ):
                break

        cursor = getattr(response, "cursor", None)

        if not cursor:
            break

    # Beide groepen combineren en werkelijk oud -> nieuw sorteren
    selected_posts = normal_posts + media_replies
    selected_posts.sort(key=get_post_datetime)

    return normal_posts, media_replies, selected_posts


# ============================================================
# UNREPOST EN REPOST
# ============================================================

def get_existing_repost_uri(post):
    """
    De URI van het eigen repost-record ophalen uit viewer.repost.
    """
    viewer = getattr(post, "viewer", None)

    if viewer is None:
        return None

    return getattr(viewer, "repost", None)


def refresh_repost(client: Client, post):
    existing_repost_uri = get_existing_repost_uri(post)

    if existing_repost_uri:
        try:
            client.delete_repost(existing_repost_uri)
            print(f"Unreposted: {post.uri}")
            time.sleep(UNREPOST_WAIT_SECONDS)

        except Exception as error:
            print(
                f"Unrepost mislukt: {post.uri} | {error}"
            )
            return False
    else:
        print(f"Nog niet gerepost: {post.uri}")

    try:
        client.repost(
            uri=post.uri,
            cid=post.cid,
        )
        print(f"Opnieuw gerepost: {post.uri}")
        return True

    except Exception as error:
        print(
            f"Repost mislukt: {post.uri} | {error}"
        )
        return False


# ============================================================
# MAIN
# ============================================================

def main():
    if not BSKY_USERNAME:
        raise RuntimeError(
            "BSKY_USERNAME ontbreekt in de GitHub Secrets."
        )

    if not BSKY_PASSWORD:
        raise RuntimeError(
            "BSKY_PASSWORD ontbreekt in de GitHub Secrets."
        )

    print("=" * 60)
    print("Big Dominio Reposter gestart")
    print(f"Login-account: {BSKY_USERNAME}")
    print(f"Target-account: {TARGET_ACCOUNT}")
    print("=" * 60)

    client = Client()
    client.login(
        BSKY_USERNAME,
        BSKY_PASSWORD,
    )

    normal_posts, media_replies, selected_posts = get_target_posts(
        client
    )

    print("")
    print(f"Gewone mediaposts gevonden: {len(normal_posts)}")
    print(f"Media-replies gevonden: {len(media_replies)}")
    print(f"Totaal geselecteerd: {len(selected_posts)}")
    print("Volgorde: oud naar nieuw")
    print("")

    successful = 0

    for number, post in enumerate(selected_posts, start=1):
        post_type = "REPLY" if is_reply(post) else "POST"

        print(
            f"[{number}/{len(selected_posts)}] "
            f"{post_type}: {post.uri}"
        )

        if refresh_repost(client, post):
            successful += 1

        time.sleep(SLEEP_SECONDS)

    print("")
    print("=" * 60)
    print(
        f"Klaar: {successful}/{len(selected_posts)} "
        f"posts succesvol gerepost."
    )
    print("=" * 60)


if __name__ == "__main__":
    main()