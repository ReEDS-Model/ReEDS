"""Build the source-code and input-data packages exposed by the admin portal."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


APP_ROOT = Path("/app")
_CONTAINER_STAGE_ROOT = APP_ROOT / "postprocessing" / "reedssurr" / "Stage2"
STAGE_ROOT = (
    _CONTAINER_STAGE_ROOT
    if _CONTAINER_STAGE_ROOT.is_dir()
    else Path(__file__).resolve().parents[2]
)
DOWNLOAD_ROOT = APP_ROOT / "admin-downloads"


def _write_archive(output_name: str, directories: tuple[str, ...]) -> None:
    output_path = DOWNLOAD_ROOT / output_name
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for directory in directories:
            root = STAGE_ROOT / directory
            if not root.is_dir():
                raise FileNotFoundError(f"Required archive directory is missing: {root}")
            for path in sorted(p for p in root.rglob("*") if p.is_file()):
                if "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                relative = path.relative_to(STAGE_ROOT)
                archive.write(path, Path("ReEDS-Proxy") / relative)


def main() -> None:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    _write_archive("reeds-proxy-source-code.zip", ("code", "data_processing", "deploy/gcp"))
    _write_archive("reeds-proxy-input-data.zip", ("inputs",))


if __name__ == "__main__":
    main()
