"""Send the daily report to Telegram.

Needs two secrets, and does nothing without them:
    TELEGRAM_BOT_TOKEN   from @BotFather
    TELEGRAM_CHAT_ID     the chat to post into (your own user id, or a channel/group id)

Standard library only, like the rest of the project.

Absence of credentials is NOT an error. The daily workflow still runs, still writes the
report, and simply says the notification was skipped — a missing token should never fail
a scan that otherwise succeeded.
"""
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.telegram.org/bot{token}/{method}"

# Telegram rejects anything over 4096 characters. Split on message boundaries rather than
# mid-line so a coupon leg is never cut in half.
MAX_LEN = 4000


def credentials():
    return os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")


def configured():
    token, chat = credentials()
    return bool(token and chat)


def _post(method, payload, token, timeout=20):
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(API.format(token=token, method=method), data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def chunks(text, limit=MAX_LEN):
    """Split on line boundaries, never mid-line."""
    out, cur = [], ""
    for line in text.split("\n"):
        # A single line longer than the limit is hard-split; nothing else can be done.
        while len(line) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


def send(text, parse_mode="HTML", disable_preview=True):
    """Send a message, splitting it if needed. Returns (sent, detail)."""
    token, chat = credentials()
    if not (token and chat):
        return False, "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — notification skipped"

    parts = chunks(text)
    for i, part in enumerate(parts, 1):
        payload = {
            "chat_id": chat,
            "text": part,
            "disable_web_page_preview": "true" if disable_preview else "false",
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            body = _post("sendMessage", payload, token)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            return False, f"HTTP {e.code} on part {i}/{len(parts)}: {detail}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return False, f"network error on part {i}/{len(parts)}: {e}"
        if not body.get("ok"):
            return False, f"telegram refused part {i}/{len(parts)}: {body}"
    return True, f"sent {len(parts)} message(s)"


def send_document(path, caption="", timeout=60, parse_mode=None):
    """Upload a file (an HTML page or the combine PDF) as a document. Returns (sent, detail).

    Telegram truncates a caption at 1024 characters and rejects the message outright if
    the cut lands inside an HTML tag, so the caption is clipped on a LINE boundary — the
    daily notice is built line by line and losing a whole trailing line is harmless,
    while losing half of a `<b>` is a 400.
    """
    token, chat = credentials()
    if not (token and chat):
        return False, "credentials not set"
    if not os.path.exists(path):
        return False, f"no such file: {path}"

    boundary = "----bwcoupon7f3a9c1e"
    with open(path, "rb") as f:
        content = f.read()
    name = os.path.basename(path)
    # Guessed from the extension rather than hardcoded: this now uploads both the picks
    # pages (.html) and the combine PDF (.pdf), and a mismatched Content-Type on the
    # multipart file part is exactly the class of "looks fine, opens wrong" bug hard rule
    # 10 exists to catch.
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"

    fields = [("chat_id", chat), ("caption", chunks(caption, 1000)[0] if caption else "")]
    if parse_mode:
        fields.append(("parse_mode", parse_mode))

    parts = []
    for key, val in fields:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}\r\n"
            .encode()
        )
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; "
        f"filename=\"{name}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(
        API.format(token=token, method="sendDocument"),
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"network error: {e}"
    return (True, "document sent") if out.get("ok") else (False, f"refused: {out}")
