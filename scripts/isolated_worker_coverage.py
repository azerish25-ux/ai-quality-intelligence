"""Test-only coverage harness; production never imports or invokes this file.

Run with Python -I and the production minimal environment/closed descriptors.
Arguments name trusted local code and the dedicated measurement destination;
untrusted images and options still arrive only through stdin.
"""

from __future__ import annotations

import hashlib
import runpy
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 5 or not sys.flags.isolated:
        raise SystemExit(2)
    worker = Path(sys.argv[1])
    expected = sys.argv[2]
    data_file = Path(sys.argv[3])
    package = Path(sys.argv[4])
    if (
        not worker.is_absolute()
        or worker.is_symlink()
        or not data_file.is_absolute()
        or data_file.is_symlink()
        or data_file.exists()
        or worker.name != "image_worker.py"
        or worker.parent != package
        or hashlib.sha256(worker.read_bytes()).hexdigest() != expected
    ):
        raise SystemExit(2)
    from coverage import Coverage

    measurement = Coverage(
        data_file=str(data_file),
        config_file=False,
        branch=True,
        source=[str(package)],
    )
    measurement.start()
    try:
        sys.argv = [str(worker)]
        runpy.run_path(str(worker), run_name="__main__")
    finally:
        measurement.stop()
        measurement.save()
    if hashlib.sha256(worker.read_bytes()).hexdigest() != expected:
        # A changed worker's measurement is never eligible for collection.
        data_file.unlink(missing_ok=True)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
