import os
import zipfile
from pathlib import Path

def make_share_bundle():
    bundle_name = "share_bundle.zip"
    base_dir = Path(__file__).resolve().parent

    # Allowed root items to bundle
    allowed_dirs = ["src", "tests", "docs", "data/out"]
    allowed_files = ["README.md", "requirements.txt", "config.py", "run_pipeline.py", "compute_accuracy.py", "CHANGES.md", "RUN_REPORT.md"]

    # Explicit exclusions
    excluded_names = {".env", ".venv", "data/cache", "logs", "__pycache__", ".pytest_cache", "backup_before_fix"}

    print(f"Creating clean {bundle_name}...")
    with zipfile.ZipFile(base_dir / bundle_name, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Add root files
        for fname in allowed_files:
            fpath = base_dir / fname
            if fpath.exists():
                zipf.write(fpath, arcname=fname)
                print(f"  + Added file: {fname}")

        # Add allowed directories
        for dname in allowed_dirs:
            dpath = base_dir / dname
            if not dpath.exists():
                continue
            for root, dirs, files in os.walk(dpath):
                # Filter out excluded directories
                rel_root = Path(root).relative_to(base_dir)
                if any(ex in str(rel_root).replace("\\", "/") for ex in [".venv", ".env", "data/cache", "logs", "__pycache__", "backup_before_fix"]):
                    continue
                for f in files:
                    if f.endswith((".pyc", ".pyo")) or f.startswith("."):
                        continue
                    if any(cred in f.lower() for cred in ["credentials", "service_account", ".key", ".pem"]):
                        continue
                    file_path = Path(root) / f
                    arcname = str(file_path.relative_to(base_dir)).replace("\\", "/")
                    zipf.write(file_path, arcname=arcname)
                    print(f"  + Added: {arcname}")

    print(f"Successfully generated {bundle_name} ({round((base_dir / bundle_name).stat().st_size / 1024, 1)} KB).")

if __name__ == "__main__":
    make_share_bundle()
