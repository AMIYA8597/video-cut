"""Upload GTA VI short clips to YouTube and manage upload queue.

Usage:
    python upload_shorts.py --status     # Check current status of clips and connected accounts
    python upload_shorts.py --upload     # Upload/queue all ready GTA VI shorts to YouTube
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from studio import accounts, auth, config, creators, ctx, jobs, posting

CLIPS_DIR = ROOT / "data" / "youtube-uploads" / "GTA6 - Shirrako walkthrough"
CREATOR_ID = "machinelearning-gta-vi"


def get_clips():
    desc_file = CLIPS_DIR / "UPLOAD - titles and descriptions.txt"
    if not desc_file.exists():
        print(f"Error: Descriptions file not found at {desc_file}")
        return []

    content = desc_file.read_text(encoding="utf-8")
    blocks = re.split(r"={40,}", content)
    clips = []

    for block in blocks:
        if "CLIP " not in block or "file:" not in block:
            continue
        m_file = re.search(r"file:\s*([^\n\r]+?\.mp4)", block)
        m_title = re.search(r"TITLE:\s*\n([^\n\r]+)", block)
        m_desc = re.search(r"DESCRIPTION:\s*\n(.*?)(?=\n\n#|$)", block, re.DOTALL)
        m_tags = re.search(r"(#\w[\w\s#]+)", block)

        if m_file and m_title:
            file_name = m_file.group(1).strip()
            title = m_title.group(1).strip()
            desc = m_desc.group(1).strip() if m_desc else ""
            tags = [t.strip("# ") for t in m_tags.group(1).split() if t.startswith("#")] if m_tags else ["Shorts", "GTA6"]

            path = CLIPS_DIR / file_name
            if path.exists():
                clips.append({
                    "file_name": file_name,
                    "path": path,
                    "title": title,
                    "description": desc,
                    "tags": tags,
                    "size_mb": round(path.stat().st_size / (1024 * 1024), 2)
                })
    return clips


def show_status():
    with ctx.as_user(auth.local_user().id):
        print("=" * 60)
        print("GTA VI SHORT CLIPS & YOUTUBE AUTO-UPLOAD STATUS")
        print("=" * 60)

        # 1. Creator workspace
        c = creators.get(CREATOR_ID)
        if c:
            print(f"\n[Creator Workspace: {c['name']}]")
            print(f"  Channel       : {c.get('channel')}")
            print(f"  Game          : {c.get('game')}")
            print(f"  Auto-Watch    : {'Enabled (Watching Live)' if c.get('auto_watch') else 'Disabled'}")
            print(f"  Auto-Post     : {'Enabled' if c.get('autopost') else 'Disabled'}")
            print(f"  Layout        : {c.get('layout')} (Gaming 9:16 vertical + Facecam)")
            print(f"  Captions      : {'Enabled' if c.get('captions') else 'Disabled'}")
            if c.get("post_footer"):
                print("  Social Footer :")
                for line in c["post_footer"].splitlines():
                    print(f"    {line}")
        else:
            print(f"\n[Warning] Creator workspace '{CREATOR_ID}' not found.")

        # 2. Connected accounts
        accs = accounts.list_accounts()
        yt_accs = [a for a in accs if a.get("platform") == "youtube"]
        print(f"\n[Connected Social Accounts]")
        if yt_accs:
            for a in yt_accs:
                print(f"  YouTube: {a.get('name')} (ID: {a.get('id')})")
        else:
            print("  YouTube: No connected account linked yet.")
            print("  -> Connect your YouTube channel in Settings > Connected apps (http://127.0.0.1:8765)")

        # 3. Ready clips
        clips = get_clips()
        print(f"\n[Ready GTA VI Completed Shorts: {len(clips)} clips]")
        for i, clip in enumerate(clips, 1):
            print(f"  {i}. {clip['title']} ({clip['size_mb']} MB)")
            print(f"     File: {clip['file_name']}")

        # 4. Post queue
        posts = posting._mine()
        scheduled = [p for p in posts if p.get("status") == "scheduled"]
        posted = [p for p in posts if p.get("status") == "posted"]
        print(f"\n[Posting Queue]")
        print(f"  Scheduled: {len(scheduled)}")
        print(f"  Posted   : {len(posted)}")
        for p in posted:
            print(f"  - {p.get('title')}: {p.get('url')}")
        print("=" * 60)


def upload_all():
    with ctx.as_user(auth.local_user().id):
        clips = get_clips()
        if not clips:
            print("No clips found to upload.")
            return

        accs = accounts.list_accounts()
        yt_accs = [a for a in accs if a.get("platform") == "youtube"]

        if not yt_accs:
            print("\n[!] No YouTube account connected yet.")
            print("To connect your YouTube channel '@MachineLearning-z6h8i':")
            print("1. Open http://127.0.0.1:8765 in your browser.")
            print("2. Go to Settings > Connected apps > YouTube.")
            print("3. Enter your Google OAuth Client ID & Secret and click Connect.")
            print("Once connected, run this script again or let PeakCut auto-post!")
            return

        acc = accounts.get(yt_accs[0]["id"])
        c = creators.get(CREATOR_ID) or creators.DEFAULTS
        footer = c.get("post_footer", "")

        print(f"\nUploading {len(clips)} clips to YouTube channel: {acc.get('name')}...")
        for i, clip in enumerate(clips, 1):
            full_desc = f"{clip['description']}\n\n{footer}\n\n" + " ".join(f"#{t}" for t in clip['tags'])
            print(f"\n[{i}/{len(clips)}] Uploading: {clip['title']}...")
            try:
                vid_id, url = accounts.youtube_upload(
                    acc, clip['path'], clip['title'], full_desc, clip['tags'], c.get("privacy", "public")
                )
                print(f"  -> SUCCESS! Uploaded as Short: {url}")
            except Exception as e:
                print(f"  -> Upload failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="GTA VI YouTube Shorts Uploader")
    parser.add_argument("--status", action="store_true", help="Show status of clips and YouTube connection")
    parser.add_argument("--upload", action="store_true", help="Upload all ready clips to connected YouTube channel")
    args = parser.parse_args()

    if args.upload:
        upload_all()
    else:
        show_status()


if __name__ == "__main__":
    main()
