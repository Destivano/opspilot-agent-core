"""Package the supplied root index.html and only its public assets for GitHub Pages."""

import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "_site"
FILES = {
    "index.html": ROOT / "index.html",
    "assets/demo.mp4": ROOT / "docs/videos/opspilot-demo.mp4",
    "assets/architecture.png": ROOT / "docs/diagrams/opspilot-aws-architecture.png",
    "assets/demo-poster.jpg": ROOT / "docs/images/demo-poster.jpg",
}


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.local = set()

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {"src", "href", "poster"} and value:
                parsed = urlsplit(value)
                if not parsed.scheme and not parsed.netloc and parsed.path:
                    self.local.add(unquote(parsed.path))


def main():
    document = FILES["index.html"].read_text(encoding="utf-8")
    references = References()
    references.feed(document)
    for reference in references.local:
        if reference.startswith("/") or reference not in FILES:
            raise ValueError(f"Unpackaged or nonrelative site asset: {reference}")
    for target, source in FILES.items():
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Missing or symlinked public asset: {source.relative_to(ROOT)}")
        destination = OUTPUT / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    (OUTPUT / ".nojekyll").touch()
    # Refuse to publish stale or unexpected files from an existing output directory.
    expected = set(FILES) | {".nojekyll"}
    actual = {p.relative_to(OUTPUT).as_posix() for p in OUTPUT.rglob("*") if p.is_file()}
    if actual != expected or any(p.is_symlink() for p in OUTPUT.rglob("*")):
        raise ValueError("Unexpected files in _site; publish only the declared public assets.")
    print(f"Packaged {len(FILES)} public files into _site/; all local HTML references resolve.")


if __name__ == "__main__":
    main()
