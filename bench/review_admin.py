"""Owner commands for the answer-key review at samskritam.ai/review.

    export REVIEW_OWNER_TOKEN=...          # the same value as in Vercel
    python bench/build_review_queue.py     # build the queue from your files
    python bench/review_admin.py upload    # send it to the site (replaces the old queue)
    python bench/review_admin.py invite "Name"      # prints that reviewer's link
    python bench/review_admin.py invites            # list invites
    python bench/review_admin.py revoke <token>
    python bench/review_admin.py publish   # pull request for public decisions
    python bench/review_admin.py pull      # all decisions -> bench/private/reviews.json

Your own link is https://samskritam.ai/review#invite=<REVIEW_OWNER_TOKEN>.
Set REVIEW_URL to try a local or preview deployment.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("REVIEW_URL", "https://samskritam.ai").rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # handled below, keeping the method, body and token


_open = urllib.request.build_opener(_NoRedirect).open


def call(method, params="", body=None):
    tok = os.environ.get("REVIEW_OWNER_TOKEN")
    if not tok:
        sys.exit("Set REVIEW_OWNER_TOKEN first (the same value as in Vercel).")
    url = f"{BASE}/api/review{params}"
    for _ in range(3):
        req = urllib.request.Request(url, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                                              "User-Agent": "samskritam-review-admin"})
        try:
            with _open(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.code in (301, 302, 307, 308) else None
            if loc:
                # e.g. samskritam.ai -> www.samskritam.ai: follow it, same request.
                url = urllib.parse.urljoin(url, loc)
                continue
            sys.exit(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    sys.exit(f"Too many redirects (last: {url}). Set REVIEW_URL to the site's address.")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "upload":
        q = json.load(open(os.path.join(ROOT, "bench/private/review-queue.json"), encoding="utf-8"))
        for i in range(0, len(q), 120):
            call("POST", body={"action": "upload", "items": q[i:i + 120], "reset": i == 0})
            print(f"  {min(i + 120, len(q))}/{len(q)}")
        print(f"Uploaded {len(q)} questions. Your link: {BASE}/review#invite=<your REVIEW_OWNER_TOKEN>")
    elif cmd == "invite" and args:
        r = call("POST", body={"action": "invite", "name": " ".join(args)})
        print(f"Invite for {r['name']} (send it privately; anyone with it can review):\n{r['link']}")
    elif cmd == "invites":
        for v in call("GET", "?action=invites")["invites"]:
            print(f"{v['name']:<30} {v['at'][:10]}  {v['token']}")
    elif cmd == "revoke" and args:
        call("POST", body={"action": "revoke", "token": args[0]})
        print("Revoked.")
    elif cmd == "publish":
        r = call("POST", body={"action": "publish"})
        print(f"Pull request: {r['url']}" if r.get("url") else "Nothing new to publish.")
    elif cmd == "pull":
        r = call("GET", "?action=export")["reviews"]
        out = os.path.join(ROOT, "bench/private/reviews.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        print(f"{len(r)} questions with decisions -> {out}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
