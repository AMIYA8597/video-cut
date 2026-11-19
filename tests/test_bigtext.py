"""The big text on the video: a person can set their own, for every clip of a video or as a creator's standing text,
for a campaign that asks for a set line. Runs against the code directly with its own empty data folder."""
import os
import sys
import tempfile

os.environ["PEAKCUT_DATA"] = tempfile.mkdtemp(prefix="pc-bigtext-")
os.environ["DATABASE_URL"] = ""
sys.path.insert(0, ".")
from studio import auth, creators, ctx, db, jobs, render  # noqa: E402

db.init()
fails = []


def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {extra}" if extra and not ok else ""))
    ok or fails.append(name)


check("the text is kept as typed, links and names included", creators.clean_hook("  Clipped from  @kai #ad  ") == "Clipped from @kai #ad")
check("it is one line", creators.clean_hook("a\nb\x00c") == "a b c")
check("it is short enough for the box", len(creators.clean_hook("x" * 200)) == 60)
check("nothing typed is nothing", creators.clean_hook(None) == "" and creators.clean_hook("   ") == "")
check("what is typed reaches the picture whole", "@kai #ad" in "\n".join(render._hook_events(render._clean("Clipped from @kai #ad"), 10, 300)))

u, _ = auth._create("bt@example.com", "Bt", password_hash="x")
with ctx.as_user(u.id):
    check("a video with no text asks the AI for one, as before", jobs.clean_options({}).get("hook_text") is None)
    check("the text given for a video is kept", jobs.clean_options({"hook_text": " SUBSCRIBE "})["hook_text"] == "SUBSCRIBE")
    check("an empty text is kept too, so it can clear a creator's", jobs.clean_options({"hook_text": ""}) == {"hook_text": ""})

    plain = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False)
    check("by default there is no custom text", plain["options"]["hook_text"] == "")
    own = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {"hook_text": "WATCH THIS"}, enqueue=False)
    check("a video can carry its own text", own["options"]["hook_text"] == "WATCH THIS")

    c = creators.create({"name": "Streamer", "hook_text": "Clipped from @streamer"})
    check("a creator keeps a standing text", creators.get(c["id"])["hook_text"] == "Clipped from @streamer")
    from_creator = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {}, enqueue=False, creator=c["id"])
    check("a video of that creator uses it", from_creator["options"]["hook_text"] == "Clipped from @streamer")
    over = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {"hook_text": "ONLY THIS ONE"}, enqueue=False, creator=c["id"])
    check("a video can use another text than the creator's", over["options"]["hook_text"] == "ONLY THIS ONE")
    cleared = jobs.create({"type": "file", "path": "", "name": "v.mp4"}, {"hook_text": ""}, enqueue=False, creator=c["id"])
    check("...or none, and the AI writes them", cleared["options"]["hook_text"] == "")
    creators.update(c["id"], {"hook_text": ""})
    check("a creator's text can be removed", creators.get(c["id"])["hook_text"] == "")

print("ALL PASSED" if not fails else f"{len(fails)} failed")
import shutil  # noqa: E402

db.engine.dispose()
shutil.rmtree(os.environ["PEAKCUT_DATA"], ignore_errors=True)
sys.exit(1 if fails else 0)
