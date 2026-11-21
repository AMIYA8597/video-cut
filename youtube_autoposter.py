#!/usr/bin/env python3
"""
YouTube Auto-Poster for GTA 6 Shorts.

Features:
- Scans clips in 'gta6-clips/'
- Generates catchy titles from filenames with #Shorts and GTA 6 hashtags
- Formats engaging descriptions including creator socials (YouTube, Instagram, Facebook) and source credit
- Computes hourly scheduling starting from the top of the next hour
- Dry-run mode: prints a clean table to terminal (time, title, file) and exports schedule.csv
- One-command YouTube OAuth connection (--connect) using local listener on registered redirect URI
- Live status inspection (--status)
- Automated upload mode (--upload, --upload --now, --upload --schedule)
- Auto-clipping pipeline integration (--clip-video <url>) to pick long videos, find viral moments with AI, and produce 9:16 Shorts with captions
- Real-time live GTA VI monitoring & auto-clipping (--live <url>)
"""

import argparse
import csv
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

# Channels & Socials
YT_CHANNEL = "https://www.youtube.com/@MachineLearning-z6h8i"
IG_PROFILE = "https://www.instagram.com/machinelearning1902/"
FB_PROFILE = "https://www.facebook.com/profile.php?id=61591774464469"

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_FOLDER = ROOT_DIR / "gta6-clips"
SCHEDULE_CSV = ROOT_DIR / "schedule.csv"
DATA_DIR = ROOT_DIR / "data"

# OAuth Google constants
OAUTH_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
OAUTH_REDIRECT_PORT = 3000
OAUTH_REDIRECT_PATH = "/api/auth/callback"
OAUTH_REDIRECT_URI = f"http://localhost:{OAUTH_REDIRECT_PORT}{OAUTH_REDIRECT_PATH}"

# Curated descriptions for GTA VI moments
CLIP_CONTEXT = {
    "driving logic": "The streamer realizes traffic laws actually matter in Vice City as the cops get heated! 🚓",
    "rescuing donnie": "The crew attempts a high-stakes rescue mission that spirals out of control in GTA VI! 💥",
    "explaining the mess": "Trying to explain to Brian how the plane got destroyed and the drop went south! ✈️😅",
    "cop tracking": "Testing out the new police tracking feature on the in-game phone in Vice City! 📱🚨",
    "caught with a hot car": "Jason gets a call about a stolen vehicle that has the police on maximum alert! 🏎️💨",
    "rent collection": "Checking in on Mandy for rent suddenly turns into an unexpected plumbing mission! 🔧😂",
    "craziest car theft": "Jason and Lucia get caught in an awkward and hilarious police encounter right after stealing a car in Vice City! 🏎️😂",
    "confessing to car theft": "The streamer accidentally confesses to grand theft auto right in front of a Vice City police officer! 🚓🤦‍♂️",
    "coffee shop": "Lucia and Jason pull off a chaotic diner stick-up in this nostalgic GTA VI flashback! ☕🔫"
}


def clean_title_from_filename(filename: str) -> str:
    """Extract clean title from file name and format for YouTube Shorts."""
    name = Path(filename).stem
    # Remove leading numbering: "01 - ", "01. ", "01_", etc.
    name = re.sub(r"^\d+\s*[-_.]\s*", "", name)
    name = name.strip()
    if not name.lower().startswith("gta 6") and not name.lower().startswith("gta vi"):
        name = f"GTA 6 - {name}"
    # Append #Shorts
    if "#Shorts" not in name and "#shorts" not in name:
        name = f"{name} #Shorts"
    return name[:100]


def build_description(title: str, filename: str) -> str:
    """Build short engaging description with creator socials and tags."""
    key = ""
    for k in CLIP_CONTEXT:
        if k in filename.lower() or k in title.lower():
            key = k
            break
    summary = CLIP_CONTEXT.get(key, "Insane moments and gameplay highlights from Grand Theft Auto VI!")

    desc = f"""{summary}

Gameplay: Shirrako (GTA 6 Gameplay Walkthrough Part 1)

Follow for more GTA VI clips:
📺 YouTube: {YT_CHANNEL}
📸 Instagram: {IG_PROFILE}
📘 Facebook: {FB_PROFILE}

#Shorts #GTA6 #GTA6Game #ViceCity #RockstarGames #Gaming #GrandTheftAutoVI"""
    return desc.strip()


def sync_rendered_clips(folder: Path):
    """Automatically copy newly rendered viral clips from PeakCut jobs into the clips folder."""
    import shutil
    base = DATA_DIR / "users" / "u_local" / "creators" / "machinelearning-gta-vi" / "videos"
    if not base.exists():
        return
    folder.mkdir(parents=True, exist_ok=True)
    existing_sizes = {f.stat().st_size for f in folder.glob("*.mp4")}
    existing_count = len(list(folder.glob("*.mp4")))

    for job_dir in sorted(base.iterdir()):
        clips_dir = job_dir / "clips"
        if not clips_dir.exists():
            continue
        for mp4 in sorted(clips_dir.glob("clip*.mp4")):
            if mp4.name.endswith(".src.mp4") or mp4.stat().st_size in existing_sizes:
                continue
            title = mp4.stem
            meta_f = mp4.with_suffix(".json")
            if meta_f.exists():
                try:
                    title = json.loads(meta_f.read_text(encoding="utf-8")).get("title", title)
                except Exception:
                    pass
            title = re.sub(r'[\/\\:*?"<>|]', '', title).strip()
            existing_count += 1
            new_name = f"{existing_count:02d} - {title}.mp4"
            dst = folder / new_name
            try:
                shutil.copy2(mp4, dst)
                existing_sizes.add(mp4.stat().st_size)
            except Exception:
                pass


def get_clips(folder: Path):
    """Retrieve all video clips sorted alphabetically, syncing any newly rendered clips."""
    sync_rendered_clips(folder)
    if not folder.exists():
        return []
    exts = {".mp4", ".mov", ".mkv", ".webm"}
    files = sorted([f for f in folder.iterdir() if f.suffix.lower() in exts and not f.name.endswith(".temp.mp4")])
    return files


def generate_schedule(clips: list, start_time: datetime = None, interval_hours: int = 1):
    """Schedule one clip every N hours starting from the top of the next hour."""
    if not start_time:
        now = datetime.now()
        start_time = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    schedule = []
    current_time = start_time
    for clip in clips:
        title = clean_title_from_filename(clip.name)
        description = build_description(title, clip.name)
        schedule.append({
            "time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "file": clip.name,
            "path": str(clip.resolve()),
            "title": title,
            "description": description,
            "tags": "Shorts, GTA6, GTA6Game, ViceCity, RockstarGames, Gaming, GrandTheftAutoVI",
            "status": "Scheduled"
        })
        current_time += timedelta(hours=interval_hours)
    return schedule


def print_table(schedule: list):
    """Render a clean, formatted ASCII table in the terminal."""
    col_time = "Scheduled Time"
    col_title = "Title"
    col_file = "File Name"

    w_time = max(len(col_time), max((len(item["time"]) for item in schedule), default=19)) + 2
    w_title = max(len(col_title), max((len(item["title"]) for item in schedule), default=35)) + 2
    w_file = max(len(col_file), max((len(item["file"]) for item in schedule), default=20)) + 2

    # Restrict title width for neat terminal display
    w_title = min(w_title, 55)

    sep = f"+{'-' * w_time}+{'-' * w_title}+{'-' * w_file}+"
    header = f"| {col_time.ljust(w_time - 2)} | {col_title.ljust(w_title - 2)} | {col_file.ljust(w_file - 2)} |"

    print("\n" + "=" * (w_time + w_title + w_file + 4))
    print(" YOUTUBE SHORTS AUTO-POSTER - GTA 6 SCHEDULE (DRY-RUN)")
    print("=" * (w_time + w_title + w_file + 4))
    print(sep)
    print(header)
    print(sep)

    for item in schedule:
        t = item["time"]
        ti = item["title"]
        if len(ti) > w_title - 2:
            ti = ti[: w_title - 5] + "..."
        f = item["file"]
        if len(f) > w_file - 2:
            f = f[: w_file - 5] + "..."
        print(f"| {t.ljust(w_time - 2)} | {ti.ljust(w_title - 2)} | {f.ljust(w_file - 2)} |")

    print(sep)
    print(f"Total clips scheduled: {len(schedule)} (1 clip every hour)")
    print("=" * (w_time + w_title + w_file + 4) + "\n")


def export_csv(schedule: list, output_path: Path):
    """Save schedule to CSV file."""
    fieldnames = ["time", "title", "file", "tags", "description", "status"]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for item in schedule:
            writer.writerow(item)
    print(f"Schedule successfully saved to: {output_path.resolve()}")


def load_google_credentials():
    """Retrieve Google OAuth Client ID and Secret."""
    apps_file = DATA_DIR / "apps.json"
    if apps_file.exists():
        try:
            data = json.loads(apps_file.read_text(encoding="utf-8"))
            google = data.get("google", {})
            if google.get("id") and google.get("secret"):
                return google["id"], google["secret"]
        except Exception:
            pass

    # Check downloads folder
    downloads = Path(os.environ.get("USERPROFILE", "")) / "Downloads"
    for secret_file in downloads.glob("client_secret_*.json"):
        try:
            data = json.loads(secret_file.read_text(encoding="utf-8"))
            web = data.get("web", {})
            if web.get("client_id") and web.get("client_secret"):
                return web["client_id"], web["client_secret"]
        except Exception:
            pass

    return None, None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    auth_code = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == OAUTH_REDIRECT_PATH:
            query = urllib.parse.parse_qs(parsed.query)
            if "code" in query:
                OAuthCallbackHandler.auth_code = query["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = """
                <html>
                <head><title>YouTube Connected</title></head>
                <body style="font-family: sans-serif; text-align: center; padding-top: 50px; background: #0f0f12; color: #f0f0f5;">
                    <div style="display: inline-block; padding: 40px; background: #1a1a24; border-radius: 12px; border: 1px solid #333;">
                        <h1 style="color: #4ade80;">YouTube Channel Connected!</h1>
                        <p style="color: #a1a1aa; font-size: 16px;">Authentication was successful. You can now close this tab and return to the terminal.</p>
                    </div>
                </body>
                </html>
                """
                self.wfile.write(html.encode("utf-8"))
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No code returned.")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def exchange_code_and_save(client_id: str, client_secret: str, code: str, redirect_uri: str):
    """Exchange auth code for tokens and store connected YouTube channel in PeakCut."""
    print("  -> Exchanging authorization code for access and refresh tokens...")
    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed ({resp.status_code}): {resp.text}")

    tok = resp.json()
    access_token = tok.get("access_token")
    refresh_token = tok.get("refresh_token")
    expires_in = tok.get("expires_in", 3600)

    # Get YouTube Channel Profile
    print("  -> Fetching YouTube channel information...")
    ch_resp = httpx.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet,statistics", "mine": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if ch_resp.status_code != 200:
        raise RuntimeError(f"Failed to query YouTube channels: {ch_resp.text}")

    ch_data = ch_resp.json()
    items = ch_data.get("items", [])
    if not items:
        raise RuntimeError("No YouTube channel found associated with this Google Account.")

    item = items[0]
    channel_id = item["id"]
    channel_title = item["snippet"]["title"]

    account_entry = {
        "id": f"yt_{channel_id}",
        "platform": "youtube",
        "name": channel_title,
        "channel_id": channel_id,
        "channel_url": f"https://www.youtube.com/channel/{channel_id}",
        "added": time.time(),
        "refresh_token": refresh_token,
        "access_token": access_token,
        "expires": time.time() + expires_in - 60,
    }

    # Save to user accounts
    accounts_file = DATA_DIR / "users" / "u_local" / "accounts" / "accounts.json"
    accounts_file.parent.mkdir(parents=True, exist_ok=True)
    existing_accounts = []
    if accounts_file.exists():
        try:
            existing_accounts = json.loads(accounts_file.read_text(encoding="utf-8"))
        except Exception:
            existing_accounts = []

    # Update or insert
    existing_accounts = [a for a in existing_accounts if a.get("id") != account_entry["id"]]
    existing_accounts.append(account_entry)
    accounts_file.write_text(json.dumps(existing_accounts, indent=1), encoding="utf-8")

    # Update Creator profile machinelearning-gta-vi to bind account
    creator_file = DATA_DIR / "users" / "u_local" / "creators" / "machinelearning-gta-vi" / "creator.json"
    if creator_file.exists():
        try:
            c = json.loads(creator_file.read_text(encoding="utf-8"))
            c["accounts"] = [account_entry["id"]]
            c["autopost"] = True
            creator_file.write_text(json.dumps(c, indent=1), encoding="utf-8")
        except Exception:
            pass

    return account_entry


def connect_youtube():
    """One-command automated YouTube channel connection."""
    client_id, client_secret = load_google_credentials()
    if not client_id or not client_secret:
        print("[!] Google OAuth credentials not found.")
        print("Please ensure client_secret.json is in your Downloads folder or data/apps.json.")
        return

    print("=" * 70)
    print(" CONNECT YOUTUBE CHANNEL (ONE-COMMAND SETUP)")
    print("=" * 70)
    print(f"Target Channel: {YT_CHANNEL}")
    print(f"Client ID     : {client_id[:16]}...{client_id[-14:]}")
    print(f"Redirect URI  : {OAUTH_REDIRECT_URI}")
    print("-" * 70)

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": OAUTH_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": "peakcut_autoposter",
    })

    server = None
    try:
        server = HTTPServer(("127.0.0.1", OAUTH_REDIRECT_PORT), OAuthCallbackHandler)
    except OSError:
        pass

    print("\n[>] Opening your browser to authenticate with Google...")
    print(f"\nIf your browser does not open automatically, visit this URL:\n\n{auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    if server:
        print(f"[>] Waiting for authorization callback on {OAUTH_REDIRECT_URI}...")
        server.timeout = 180
        start_wait = time.time()
        while not OAuthCallbackHandler.auth_code and (time.time() - start_wait < 180):
            server.handle_request()

        if OAuthCallbackHandler.auth_code:
            code = OAuthCallbackHandler.auth_code
            try:
                acc = exchange_code_and_save(client_id, client_secret, code, OAUTH_REDIRECT_URI)
                print("\n" + "=" * 70)
                print(f" [SUCCESS] Connected YouTube Channel: {acc['name']}")
                print(f" Channel ID: {acc.get('channel_id')}")
                print(" Auto-posting enabled for creator: 'MachineLearning GTA VI'")
                print("=" * 70)
                print("\nReady! To start uploading clips to YouTube, run:")
                print("  python youtube_autoposter.py --upload --now")
                return
            except Exception as e:
                print(f"\n[!] Token exchange error: {e}")
                return

    # Fallback to manual entry
    print("\n[>] If the browser redirect didn't catch, paste the full redirect URL or the 'code' parameter below:")
    try:
        user_input = input("Enter Code or Redirect URL: ").strip()
    except (EOFError, KeyboardInterrupt):
        return

    if not user_input:
        print("Cancelled.")
        return

    code = user_input
    if "code=" in user_input:
        m = re.search(r"code=([^&]+)", user_input)
        if m:
            code = urllib.parse.unquote(m.group(1))

    try:
        acc = exchange_code_and_save(client_id, client_secret, code, OAUTH_REDIRECT_URI)
        print("\n" + "=" * 70)
        print(f" [SUCCESS] Connected YouTube Channel: {acc['name']}")
        print(f" Channel ID: {acc.get('channel_id')}")
        print("=" * 70)
        print("\nReady! To start uploading clips, run:")
        print("  python youtube_autoposter.py --upload --now")
    except Exception as e:
        print(f"[!] Error connecting YouTube: {e}")


def check_status():
    """Print full status of accounts, ready clips, and scheduled queue."""
    print("=" * 70)
    print(" GTA VI YOUTUBE AUTO-POSTER & CLIPPING PIPELINE STATUS")
    print("=" * 70)

    # 1. Accounts
    accounts_file = DATA_DIR / "users" / "u_local" / "accounts" / "accounts.json"
    connected_yt = []
    if accounts_file.exists():
        try:
            accs = json.loads(accounts_file.read_text(encoding="utf-8"))
            connected_yt = [a for a in accs if a.get("platform") == "youtube"]
        except Exception:
            pass

    print("[Connected YouTube Channels]")
    if connected_yt:
        for a in connected_yt:
            print(f"  * {a.get('name')} (ID: {a.get('id')})")
    else:
        print("  * None connected yet.")
        print("  -> Connect instantly with: python youtube_autoposter.py --connect")

    # 2. Clips
    clips = get_clips(DEFAULT_FOLDER)
    print(f"\n[Ready GTA VI Clips in '{DEFAULT_FOLDER.name}': {len(clips)} clips]")
    for i, c in enumerate(clips, 1):
        size_mb = round(c.stat().st_size / (1024 * 1024), 2)
        print(f"  {i}. {c.name} ({size_mb} MB)")

    # 3. Schedule
    if SCHEDULE_CSV.exists():
        print(f"\n[Schedule Table: {SCHEDULE_CSV.name}]")
        with SCHEDULE_CSV.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                print(f"  * {row.get('time')} | {row.get('title')} | Status: {row.get('status')}")
    print("=" * 70)


def upload_clips(immediate: bool = False):
    """Upload scheduled clips to the connected YouTube channel."""
    accounts_file = DATA_DIR / "users" / "u_local" / "accounts" / "accounts.json"
    if not accounts_file.exists():
        print("[!] No YouTube account connected yet.")
        print("Run with --connect to link your YouTube channel in one command:")
        print("  python youtube_autoposter.py --connect")
        return

    accs = json.loads(accounts_file.read_text(encoding="utf-8"))
    yt_accs = [a for a in accs if a.get("platform") == "youtube"]
    if not yt_accs:
        print("[!] No YouTube channel connected.")
        print("Run: python youtube_autoposter.py --connect")
        return

    acc = yt_accs[0]
    print(f"Uploading to YouTube Channel: {acc.get('name')}...")

    # Load schedule
    clips = get_clips(DEFAULT_FOLDER)
    schedule = generate_schedule(clips)

    sys.path.insert(0, str(ROOT_DIR))
    from studio import accounts as studio_accounts

    for i, item in enumerate(schedule, 1):
        if not immediate:
            sched_dt = datetime.strptime(item["time"], "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            if sched_dt > now:
                wait_sec = (sched_dt - now).total_seconds()
                print(f"[{i}/{len(schedule)}] Waiting until {item['time']} ({int(wait_sec)}s) to upload...")
                time.sleep(min(wait_sec, 3600))

        print(f"\n[{i}/{len(schedule)}] Uploading {item['file']} -> {item['title']}...")
        try:
            video_id, url = studio_accounts.youtube_upload(
                acc,
                Path(item["path"]),
                item["title"],
                item["description"],
                [t.strip() for t in item["tags"].split(",")],
                "public",
            )
            print(f"  [SUCCESS] Uploaded as Short: {url}")
            item["status"] = f"Uploaded: {url}"
        except Exception as e:
            print(f"  [FAILED] {e}")
            item["status"] = f"Failed: {e}"

    export_csv(schedule, SCHEDULE_CSV)


def clip_long_video(video_url: str):
    """Submit a long video URL to PeakCut's AI pipeline to extract viral shorts."""
    sys.path.insert(0, str(ROOT_DIR))
    from studio import auth, ctx, jobs

    with ctx.as_user(auth.local_user().id):
        print(f"Submitting long video for viral clipping: {video_url}")
        job = jobs.create(
            {"type": "url", "url": video_url, "name": video_url},
            {
                "max_clips": 6,
                "min_len": 15,
                "max_len": 60,
                "style": "bounce",
                "layout": "gameplay",
                "quality": 720,
                "captions": True,
            },
            creator="machinelearning-gta-vi",
        )
        print(f"Job successfully created: {job['id']}")
        print("PeakCut AI is now downloading, transcribing, and cutting viral moments.")
        print(f"Monitor job status with: python youtube_autoposter.py --status")


def start_live_monitoring(url: str):
    """Start live stream watcher and auto-clipper for GTA VI."""
    sys.path.insert(0, str(ROOT_DIR))
    from studio import auth, creators, ctx, live

    with ctx.as_user(auth.local_user().id):
        c = creators.get("machinelearning-gta-vi")
        if not c:
            print("[!] Creator 'machinelearning-gta-vi' not found.")
            return
        print(f"Starting real-time live monitor on: {url}")
        print(f"Game: {c.get('game')}")
        print(f"Layout: {c.get('layout')} (9:16 Vertical Gameplay + Facecam)")
        print(f"Captions: {c.get('style')} animated bounce captions")
        print(f"Auto-post: {'Enabled' if c.get('autopost') else 'Disabled'}")
        try:
            job = live.start_session(c, url)
            print(f"[SUCCESS] Live recording session started! Session ID: {job['id']}")
            print("PeakCut AI is now watching the stream, monitoring chat/signals for viral spikes, and auto-clipping shorts.")
        except Exception as e:
            print(f"[!] Could not start live session: {e}")


def main():
    parser = argparse.ArgumentParser(description="YouTube Shorts Auto-Poster for GTA 6 Clips")
    parser.add_argument("--folder", type=str, default=str(DEFAULT_FOLDER), help="Path to clips folder")
    parser.add_argument("--dry-run", action="store_true", help="Run without uploading (show schedule table & write CSV)")
    parser.add_argument("--connect", action="store_true", help="Connect YouTube channel with one command")
    parser.add_argument("--status", action="store_true", help="Show pipeline and connection status")
    parser.add_argument("--sync", action="store_true", help="Sync latest AI-rendered clips from PeakCut jobs")
    parser.add_argument("--interval", type=int, default=1, help="Hours between scheduled clips (default: 1)")
    parser.add_argument("--start", type=str, help="Start time in 'YYYY-MM-DD HH:MM:SS' format (default: top of next hour)")
    parser.add_argument("--upload", action="store_true", help="Upload queued clips to connected YouTube channel")
    parser.add_argument("--now", action="store_true", help="Upload immediately instead of waiting for hourly schedule")
    parser.add_argument("--clip-video", type=str, help="Submit a long GTA VI video URL to auto-clip viral moments")
    parser.add_argument("--live", type=str, help="Start live GTA VI stream monitoring and auto-clipping")

    args = parser.parse_args()

    if args.connect:
        connect_youtube()
        return

    if args.status:
        check_status()
        return

    if args.clip_video:
        clip_long_video(args.clip_video)
        return

    if args.live:
        start_live_monitoring(args.live)
        return

    folder = Path(args.folder)
    if args.sync:
        sync_rendered_clips(folder)
        print(f"Synced clips in '{folder.name}'. Ready clips: {len(get_clips(folder))}")
        return

    clips = get_clips(folder)
    if not clips:
        print(f"No video clips found in '{folder}'. Make sure .mp4 files exist in the folder.")
        return

    start_dt = None
    if args.start:
        try:
            start_dt = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            print("[!] Invalid --start format. Use 'YYYY-MM-DD HH:MM:SS'")
            return

    schedule = generate_schedule(clips, start_time=start_dt, interval_hours=args.interval)

    if args.upload:
        upload_clips(immediate=args.now)
    else:
        # Dry-run is default
        print_table(schedule)
        export_csv(schedule, SCHEDULE_CSV)
        print("Ready! To connect your YouTube channel later, simply run:")
        print("  python youtube_autoposter.py --connect")


if __name__ == "__main__":
    main()
