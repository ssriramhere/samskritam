"""Fetch the Vidyut data files this project needs (kosha, prakriya, chandas)
without installing anything: standard library only.

    python engine/fetch_data.py [target_dir]
"""
import io
import os
import sys
import urllib.request
import zipfile

URL = "https://github.com/ambuda-org/vidyut/releases/download/py-0.4.0/data-0.4.0.zip"
NEEDED = ("kosha/", "prakriya/", "chandas/")


def ensure(target: str) -> str:
    """Download and unpack the data into target unless it is already there."""
    if os.path.exists(os.path.join(target, "kosha", "padas.fst")):
        return target
    os.makedirs(target, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=60) as r:
        blob = io.BytesIO(r.read())
    with zipfile.ZipFile(blob) as z:
        for name in z.namelist():
            inner = name
            if inner.startswith(NEEDED) and not name.endswith("/"):
                dest = os.path.join(target, inner)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(name) as src, open(dest + ".part", "wb") as out:
                    out.write(src.read())
                os.replace(dest + ".part", dest)
    return target


if __name__ == "__main__":
    print(ensure(sys.argv[1] if len(sys.argv) > 1 else "vidyut-data"))
