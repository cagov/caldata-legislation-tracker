"""Land California leginfo bulk-download zips into the Unity Catalog raw zone.

Runs as the `land_raw` Job task before the Lakeflow pipeline (see
`resources/legislation.job.yml`). It streams the official public zips from
downloads.leginfo.legislature.ca.gov straight into a UC volume and records a
manifest for provenance.

It deliberately does NOT extract the zips: the session zip explodes into ~200k
tiny `.lob` files and writing those onto the FUSE-mounted volume is pathologically
slow. Unzipping happens in the bronze pipeline instead, in-memory and parallel
(see `bronze/leginfo_bronze.py` and `ca-leginfo-bulk-download.md` §5).

Intentionally stdlib-only (urllib/hashlib) so the serverless task needs no extra
environment dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "https://downloads.leginfo.legislature.ca.gov"
# Identify the fetcher so the public server sees a real UA rather than the
# default urllib string; the source is unauthenticated plain HTTPS.
USER_AGENT = "caldata-legislation-tracker/land_raw (ian.rose@innovation.ca.gov)"
CHUNK_BYTES = 1 << 20  # 1 MiB streaming chunks keep peak memory flat on ~1 GB zips.


@dataclass
class FileResult:
    """One landed file's provenance, serialized into the run manifest."""

    filename: str
    source_url: str
    last_modified: str | None
    content_length: int | None
    bytes_downloaded: int
    sha256: str
    zip_path: str


def _utc_now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def download(url: str, dest: Path) -> FileResult:
    """Stream `url` to `dest`, returning provenance.

    Raises on any HTTP error and on a size mismatch versus Content-Length, so a
    truncated or failed download never lands silently.
    """
    request = Request(url, headers={"User-Agent": USER_AGENT})
    sha256 = hashlib.sha256()
    bytes_downloaded = 0

    dest.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(request) as response, dest.open("wb") as out:
        content_length = response.headers.get("Content-Length")
        last_modified = response.headers.get("Last-Modified")
        expected = int(content_length) if content_length is not None else None
        while chunk := response.read(CHUNK_BYTES):
            out.write(chunk)
            sha256.update(chunk)
            bytes_downloaded += len(chunk)

    if expected is not None and bytes_downloaded != expected:
        raise OSError(
            f"{url}: downloaded {bytes_downloaded} bytes but Content-Length was {expected}"
        )

    return FileResult(
        filename=dest.name,
        source_url=url,
        last_modified=last_modified,
        content_length=expected,
        bytes_downloaded=bytes_downloaded,
        sha256=sha256.hexdigest(),
        zip_path=str(dest),
    )


def land(files: list[str], base_url: str, volume_root: Path, run_mode: str) -> Path:
    """Download each file into the raw zone, then write the run manifest."""
    zips_dir = volume_root / "zips"
    manifests_dir = volume_root / "manifests"

    fetched_at = datetime.now(timezone.utc).isoformat()
    results: list[FileResult] = []
    for filename in files:
        url = f"{base_url.rstrip('/')}/{filename}"
        print(f"Downloading {url}", flush=True)
        result = download(url, zips_dir / filename)
        print(f"  {result.bytes_downloaded:,} bytes  sha256={result.sha256}", flush=True)
        results.append(result)

    manifest = {
        "run_mode": run_mode,
        "base_url": base_url,
        "fetched_at_utc": fetched_at,
        "files": [asdict(r) for r in results],
    }
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests_dir / f"manifest_{_utc_now_stamp()}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"Wrote manifest {manifest_path}", flush=True)
    return manifest_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, help="Unity Catalog catalog name.")
    parser.add_argument("--schema", required=True, help="Schema holding the raw volume.")
    parser.add_argument("--volume", required=True, help="Volume name for the raw zone.")
    parser.add_argument(
        "--files",
        required=True,
        help="Comma-separated leginfo zip filenames, e.g. 'pubinfo_load.zip,pubinfo_2025.zip'.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Source directory index URL.")
    parser.add_argument(
        "--run-mode",
        default="initial",
        help="Provenance label recorded in the manifest (e.g. initial, daily, weekly).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    files = [f.strip() for f in args.files.split(",") if f.strip()]
    if not files:
        raise SystemExit("--files must name at least one zip")

    volume_root = Path(f"/Volumes/{args.catalog}/{args.schema}/{args.volume}")
    land(files=files, base_url=args.base_url, volume_root=volume_root, run_mode=args.run_mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
