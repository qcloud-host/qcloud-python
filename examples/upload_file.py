"""Upload a local model input without submitting generation."""
import sys
from pathlib import Path
from qcloud_ai import QCloud

if len(sys.argv) < 2:
    raise SystemExit("Usage: python upload_file.py <local-path> [content-type]")
with QCloud() as client:
    file = client.generation.files.upload(
        Path(sys.argv[1]), content_type=sys.argv[2] if len(sys.argv) > 2 else "application/octet-stream",
        max_bytes=64 * 1024 * 1024,
    )
    print({"id": file.id, "input_reference": file.url, "size": file.size_bytes, "sha256": file.sha256})
