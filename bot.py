import os, sys, json, time, requests, urllib.parse
from m3u_parser import fetch_m3u, Channel
from typing import List, Dict

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ["BOT_TOKEN"]
ADMIN_ID    = int(os.environ["ADMIN_ID"])   # তোমার Telegram user ID
PLAYER_URL  = os.environ.get("PLAYER_URL", "").rstrip("/")  # GitHub Pages URL
CONFIG_FILE = "config.json"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ── Config helpers ─────────────────────────────────────────────────────────────
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            return json.load(open(CONFIG_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {"m3u_sources": [], "offset": 0}

def save_config(cfg: dict):
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ── Telegram API ───────────────────────────────────────────────────────────────
def api(method: str, **kwargs):
    try:
        r = requests.post(f"{BASE_URL}/{method}", json=kwargs, timeout=15)
        return r.json()
    except Exception as e:
        print(f"[ERROR] api/{method}: {e}")
        return {}

def send(chat_id, text, **kwargs):
    return api("sendMessage", chat_id=chat_id, text=text,
                parse_mode="HTML", **kwargs)

def send_chunks(chat_id, text, **kwargs):
    """Send long messages in chunks of 4000 chars."""
    for i in range(0, len(text), 4000):
        send(chat_id, text[i:i+4000], **kwargs)

# ── Channel helpers ────────────────────────────────────────────────────────────
def load_channels(sources: list) -> List[Channel]:
    all_ch = []
    for url in sources:
        print(f"[INFO] Loading: {url}")
        chs = fetch_m3u(url)
        all_ch.extend(chs)
        print(f"[INFO] Got {len(chs)} channels from {url}")
    return all_ch

def get_groups(channels: List[Channel]) -> Dict[str, List[Channel]]:
    groups: Dict[str, List[Channel]] = {}
    for ch in channels:
        g = ch.group or "অন্যান্য"
        groups.setdefault(g, []).append(ch)
    return dict(sorted(groups.items()))

# ── Inline keyboard helper ─────────────────────────────────────────────────────
def keyboard(rows: list) -> dict:
    """rows = [[("text","callback_data"), ...], ...]
    A row item can also be a 3-tuple ("text", None, web_app_url) for a Web App button."""
    kb_rows = []
    for row in rows:
        kb_row = []
        for item in row:
            if len(item) == 3:
                text, _, web_app_url = item
                kb_row.append({"text": text, "web_app": {"url": web_app_url}})
            else:
                text, data = item
                kb_row.append({"text": text, "callback_data": data})
        kb_rows.append(kb_row)
    return {"inline_keyboard": kb_rows}

def play_url(ch) -> str:
    """Build the Telegram Mini App player URL for a channel."""
    if not PLAYER_URL:
        return ""
    q = urllib.parse.urlencode({"url": ch.url, "name": ch.name})
    return f"{PLAYER_URL}/player.html?{q}"

# ── Sessions (page state per user) ────────────────────────────────────────────
# key: chat_id → {"group": str, "page": int}
sessions: Dict[int, dict] = {}

PAGE_SIZE = 10  # channels per page

# ── Command handlers ───────────────────────────────────────────────────────────
HELP_TEXT = """
🎬 <b>IPTV Bot — সাহায্য</b>

<b>📺 দর্শক Commands:</b>
/channels — সব ক্যাটেগরি দেখো
/search &lt;নাম&gt; — চ্যানেল খোঁজো
/live &lt;নাম&gt; — সরাসরি স্ট্রিম লিঙ্ক পাও
/sources — সক্রিয় M3U সোর্স দেখো
/total — মোট চ্যানেল সংখ্যা

<b>🔧 Admin Commands:</b>
/add &lt;M3U URL&gt; — নতুন M3U যোগ করো
/remove &lt;নম্বর&gt; — M3U সরাও
/refresh — চ্যানেল লিস্ট আবার লোড করো

<b>💡 Tips:</b>
• /search bd — বাংলাদেশি চ্যানেল
• /search news — সব নিউজ চ্যানেল
• /live Star Jalsha — সরাসরি লিঙ্ক
"""

def cmd_start(chat_id: int, channels: list):
    total = len(channels)
    groups = len(get_groups(channels))
    send(chat_id, f"""
🎬 <b>IPTV Bot-এ স্বাগতম!</b>

📺 <b>{total}</b> টি চ্যানেল উপলব্ধ
📂 <b>{groups}</b> টি ক্যাটেগরি

/channels — চ্যানেল ব্রাউজ করো
/search &lt;নাম&gt; — খোঁজো
/help — সাহায্য
""")

def cmd_channels(chat_id: int, channels: list):
    groups = get_groups(channels)
    if not groups:
        send(chat_id, "❌ কোনো চ্যানেল নেই। Admin-কে M3U যোগ করতে বলো।")
        return

    lines = ["📂 <b>ক্যাটেগরি / Categories</b>\n"]
    rows = []
    for i, (grp, chs) in enumerate(groups.items(), 1):
        lines.append(f"{i}. {grp} ({len(chs)}টি)")
        rows.append((f"{grp[:20]} ({len(chs)})", f"grp|{grp[:50]}|0"))
        if len(rows) == 2:
            # Will use inline buttons for first 20 groups
            pass

    # Show category list as text + inline buttons (up to 20 groups)
    group_list = list(groups.items())[:20]
    btn_rows = []
    for j in range(0, len(group_list), 2):
        row = []
        for grp, chs in group_list[j:j+2]:
            row.append((f"{grp[:18]} ({len(chs)})", f"grp|{grp[:50]}|0"))
        btn_rows.append(row)

    send(chat_id,
         "\n".join(lines[:21]),
         reply_markup=keyboard(btn_rows))

def cmd_group_page(chat_id: int, group: str, page: int, channels: list, message_id=None):
    groups = get_groups(channels)
    chs = groups.get(group, [])
    if not chs:
        send(chat_id, f"❌ '{group}' ক্যাটেগরি পাওয়া যায়নি।")
        return

    total_pages = max(1, (len(chs) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end   = start + PAGE_SIZE
    chunk = chs[start:end]

    lines = [f"📺 <b>{group}</b> — পৃষ্ঠা {page+1}/{total_pages}\n"]
    btn_rows = []
    for ch in chunk:
        lines.append(f"• {ch.name}")
        row = [(f"{ch.name[:22]}", f"ch|{ch.name[:60]}")]
        p_url = play_url(ch)
        if p_url:
            row.append(("▶️ Play", None, p_url))
        btn_rows.append(row)

    # Pagination
    nav = []
    if page > 0:
        nav.append(("◀ আগে", f"grp|{group[:50]}|{page-1}"))
    if page < total_pages - 1:
        nav.append(("পরে ▶", f"grp|{group[:50]}|{page+1}"))
    if nav:
        btn_rows.append(nav)
    btn_rows.append([("🔙 ক্যাটেগরিতে ফিরো", "back|categories")])

    text = "\n".join(lines)
    if message_id:
        api("editMessageText", chat_id=chat_id, message_id=message_id,
            text=text, parse_mode="HTML",
            reply_markup=keyboard(btn_rows))
    else:
        send(chat_id, text, reply_markup=keyboard(btn_rows))

def cmd_channel_detail(chat_id: int, ch_name: str, channels: list, message_id=None):
    found = [c for c in channels if c.name.lower() == ch_name.lower()]
    if not found:
        found = [c for c in channels if ch_name.lower() in c.name.lower()]
    if not found:
        msg = f"❌ '{ch_name}' নামে কোনো চ্যানেল পাওয়া যায়নি।"
        if message_id:
            api("editMessageText", chat_id=chat_id, message_id=message_id,
                text=msg, parse_mode="HTML")
        else:
            send(chat_id, msg)
        return

    ch = found[0]
    text = f"""
📺 <b>{ch.name}</b>

📂 ক্যাটেগরি : {ch.group}
🌐 ভাষা     : {ch.language or 'অজানা'}
🏳 দেশ      : {ch.country or 'অজানা'}

🔗 <b>Stream Link:</b>
<code>{ch.url}</code>

📋 VLC/MX Player-এ link টা paste করেও দেখা যাবে!
"""
    rows = []
    p_url = play_url(ch)
    if p_url:
        rows.append([(f"▶️ বট-এর ভেতরেই Play করো", None, p_url)])
    rows.append([("🔙 ফিরে যাও", f"grp|{ch.group[:50]}|0")])
    btns = keyboard(rows)
    if message_id:
        api("editMessageText", chat_id=chat_id, message_id=message_id,
            text=text, parse_mode="HTML", reply_markup=btns)
    else:
        send(chat_id, text, reply_markup=btns)

def cmd_search(chat_id: int, query: str, channels: list):
    if not query.strip():
        send(chat_id, "❌ কী খুঁজতে চাও লেখো। যেমন: /search star")
        return

    q = query.lower()
    results = [c for c in channels
               if q in c.name.lower() or q in c.group.lower()
               or q in (c.language or "").lower()
               or q in (c.country or "").lower()]

    if not results:
        send(chat_id, f"❌ '<b>{query}</b>' দিয়ে কোনো চ্যানেল পাওয়া যায়নি।")
        return

    lines = [f"🔍 <b>'{query}'</b> — {len(results)} টি ফলাফল\n"]
    btn_rows = []
    for ch in results[:20]:
        lines.append(f"• {ch.name} ({ch.group})")
        row = [(f"{ch.name[:22]}", f"ch|{ch.name[:60]}")]
        p_url = play_url(ch)
        if p_url:
            row.append(("▶️ Play", None, p_url))
        btn_rows.append(row)

    if len(results) > 20:
        lines.append(f"\n... এবং আরো {len(results)-20} টি")

    send(chat_id, "\n".join(lines), reply_markup=keyboard(btn_rows))

def cmd_live(chat_id: int, name: str, channels: list):
    if not name.strip():
        send(chat_id, "❌ চ্যানেলের নাম দাও। যেমন: /live Star Jalsha")
        return
    cmd_channel_detail(chat_id, name, channels)

def cmd_sources(chat_id: int, sources: list):
    if not sources:
        send(chat_id, "❌ কোনো M3U সোর্স নেই। /add দিয়ে যোগ করো।")
        return
    lines = ["📋 <b>M3U সোর্স সমূহ:</b>\n"]
    for i, src in enumerate(sources, 1):
        lines.append(f"{i}. <code>{src}</code>")
    send(chat_id, "\n".join(lines))

def cmd_total(chat_id: int, channels: list):
    groups = get_groups(channels)
    lines = [f"📊 <b>মোট চ্যানেল: {len(channels)}</b>\n",
             f"📂 মোট ক্যাটেগরি: {len(groups)}\n"]
    for grp, chs in list(groups.items())[:15]:
        lines.append(f"• {grp}: {len(chs)}টি")
    if len(groups) > 15:
        lines.append(f"... এবং আরো {len(groups)-15} টি ক্যাটেগরি")
    send(chat_id, "\n".join(lines))

# ── Admin handlers ─────────────────────────────────────────────────────────────
def admin_add(chat_id: int, url: str, cfg: dict) -> List[Channel]:
    url = url.strip()
    if not url.startswith("http"):
        send(chat_id, "❌ সঠিক URL দাও (http দিয়ে শুরু)।")
        return []
    if url in cfg["m3u_sources"]:
        send(chat_id, "⚠️ এই সোর্স আগে থেকেই আছে।")
        return []
    send(chat_id, f"⏳ M3U লোড করছি...\n<code>{url}</code>")
    chs = fetch_m3u(url)
    if not chs:
        send(chat_id, "❌ M3U লোড হয়নি। URL ঠিক আছে কিনা দেখো।")
        return []
    cfg["m3u_sources"].append(url)
    save_config(cfg)
    send(chat_id, f"✅ যোগ হয়েছে! {len(chs)} টি চ্যানেল পাওয়া গেছে।")
    return chs

def admin_remove(chat_id: int, idx: str, cfg: dict):
    try:
        i = int(idx) - 1
        if 0 <= i < len(cfg["m3u_sources"]):
            removed = cfg["m3u_sources"].pop(i)
            save_config(cfg)
            send(chat_id, f"✅ সরানো হয়েছে:\n<code>{removed}</code>")
        else:
            send(chat_id, "❌ সঠিক নম্বর দাও।")
    except ValueError:
        send(chat_id, "❌ সংখ্যা দাও। যেমন: /remove 1")

# ── Main polling loop ──────────────────────────────────────────────────────────
def run(duration_minutes: int = 350, interval_seconds: int = 2):
    cfg = load_config()
    print(f"[INFO] Starting with {len(cfg['m3u_sources'])} sources")

    # Load channels
    channels: List[Channel] = load_channels(cfg["m3u_sources"])
    print(f"[INFO] Loaded {len(channels)} channels total")

    offset  = cfg.get("offset", 0)
    end_time = time.time() + duration_minutes * 60

    while time.time() < end_time:
        try:
            resp = requests.get(
                f"{BASE_URL}/getUpdates",
                params={"offset": offset, "timeout": interval_seconds},
                timeout=interval_seconds + 5
            ).json()
        except Exception as e:
            print(f"[WARN] getUpdates: {e}")
            time.sleep(5)
            continue

        for update in resp.get("result", []):
            offset = update["update_id"] + 1
            cfg["offset"] = offset

            # ── Callback query (inline button) ────────────────────────────────
            if "callback_query" in update:
                cq      = update["callback_query"]
                cq_id   = cq["id"]
                data    = cq.get("data", "")
                cid     = cq["message"]["chat"]["id"]
                mid     = cq["message"]["message_id"]

                api("answerCallbackQuery", callback_query_id=cq_id)

                if data.startswith("grp|"):
                    _, grp, pg = data.split("|", 2)
                    cmd_group_page(cid, grp, int(pg), channels, mid)

                elif data.startswith("ch|"):
                    ch_name = data[3:]
                    cmd_channel_detail(cid, ch_name, channels, mid)

                elif data == "back|categories":
                    cmd_channels(cid, channels)

                continue

            # ── Text message ──────────────────────────────────────────────────
            msg = update.get("message") or update.get("edited_message")
            if not msg:
                continue

            cid  = msg["chat"]["id"]
            text = (msg.get("text") or "").strip()
            uid  = msg["from"]["id"]

            if not text:
                continue

            parts = text.split(None, 1)
            cmd   = parts[0].lower().split("@")[0]
            args  = parts[1] if len(parts) > 1 else ""

            print(f"[INFO] cmd={cmd} from uid={uid}")

            if cmd in ("/start", "/help"):
                if cmd == "/start":
                    cmd_start(cid, channels)
                else:
                    send(cid, HELP_TEXT)

            elif cmd == "/channels":
                cmd_channels(cid, channels)

            elif cmd == "/search":
                cmd_search(cid, args, channels)

            elif cmd == "/live":
                cmd_live(cid, args, channels)

            elif cmd == "/sources":
                cmd_sources(cid, cfg["m3u_sources"])

            elif cmd == "/total":
                cmd_total(cid, channels)

            elif cmd == "/refresh":
                if uid != ADMIN_ID:
                    send(cid, "❌ শুধু Admin এই command ব্যবহার করতে পারবে।")
                    continue
                send(cid, "⏳ চ্যানেল লিস্ট reload করছি...")
                channels = load_channels(cfg["m3u_sources"])
                send(cid, f"✅ {len(channels)} টি চ্যানেল লোড হয়েছে!")

            elif cmd == "/add":
                if uid != ADMIN_ID:
                    send(cid, "❌ শুধু Admin এই command ব্যবহার করতে পারবে।")
                    continue
                if not args:
                    send(cid, "❌ M3U URL দাও। যেমন:\n/add http://example.com/list.m3u")
                    continue
                new_chs = admin_add(cid, args, cfg)
                if new_chs:
                    channels.extend(new_chs)

            elif cmd == "/remove":
                if uid != ADMIN_ID:
                    send(cid, "❌ শুধু Admin এই command ব্যবহার করতে পারবে।")
                    continue
                admin_remove(cid, args, cfg)
                channels = load_channels(cfg["m3u_sources"])

        # Save offset periodically
        save_config(cfg)
        time.sleep(1)

    print("[INFO] Loop finished.")

if __name__ == "__main__":
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 350
    run(duration_minutes=dur)
