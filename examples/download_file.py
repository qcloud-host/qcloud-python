"""Download an existing generated asset without submitting a new job."""
import os

from qcloud_ai import QCloud

with QCloud() as client:
    with client.generation.files.download(
        os.environ["QCLOUD_JOB_ID"], os.environ["QCLOUD_ASSET_ID"],
        max_bytes=64 * 1024 * 1024, timeout=120,
    ) as file:
        with open("output.bin", "xb") as output:
            for chunk in file:
                output.write(chunk)
