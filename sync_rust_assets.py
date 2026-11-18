#!/usr/bin/env python3
r"""
Rust Asset Sync & Optimization Script
-------------------------------------
Automates synchronization of Rust item icons from the local Rust game installation
(C:\Program Files (x86)\Steam\steamapps\common\Rust\Bundles\items)
to the industrial-hub-assets repository.

Features:
- Checks Steam AppManifest (BuildID / LastUpdated) to detect wipe/game updates.
- Maintains dual-hash tracking in sync_state.json:
    * sourceHash: SHA-256 of the uncompressed 512x512 original in Rust game files
    * compressedHash: SHA-256 of the 128x128 optimized PNG in industrial-hub-assets
- Detects new and modified items by comparing source hashes.
- Resizes new/modified images to 128x128 with Lanczos resampling and PNG optimization.
- Leaves untouched images bit-for-bit identical to avoid invalidating client cache.
- Updates manifest.json for Industrial Hub client auto-sync.
- Generates a report of new/modified items and companion item metadata.
"""

import os
import sys
import json
import re
import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image

DEFAULT_RUST_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Rust\Bundles\items")
DEFAULT_STEAM_ACF = Path(r"C:\Program Files (x86)\Steam\steamapps\appmanifest_252490.acf")
DEFAULT_ASSETS_DIR = Path(r"C:\Users\dimav\source\repos\industrial-hub-assets")
DEFAULT_ITEMS_DIR = DEFAULT_ASSETS_DIR / "items"
DEFAULT_MANIFEST = DEFAULT_ASSETS_DIR / "manifest.json"
DEFAULT_SYNC_STATE = DEFAULT_ASSETS_DIR / "sync_state.json"

TARGET_SIZE = (128, 128)

def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def get_steam_build_info(acf_path: Path):
    if not acf_path.exists():
        return None, None
    try:
        content = acf_path.read_text(encoding="utf-8", errors="ignore")
        build_id = re.search(r'"buildid"\s+"(\d+)"', content, re.IGNORECASE)
        last_updated = re.search(r'"LastUpdated"\s+"(\d+)"', content, re.IGNORECASE)
        b_id = build_id.group(1) if build_id else "unknown"
        l_up = int(last_updated.group(1)) if last_updated else None
        return b_id, l_up
    except Exception as e:
        print(f"[Warning] Failed to read Steam manifest: {e}")
        return None, None

def load_json(path: Path, default=None):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Warning] Failed to parse JSON from {path}: {e}")
    return default if default is not None else {}

def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def resize_and_optimize(source_path: Path, dest_path: Path):
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as img:
        # Ensure RGBA for transparent background icons
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        resized = img.resize(TARGET_SIZE, Image.Resampling.LANCZOS)
        resized.save(dest_path, "PNG", optimize=True)

def main():
    parser = argparse.ArgumentParser(description="Synchronize Rust item icons to industrial-hub-assets.")
    parser.add_argument("--force", action="store_true", help="Run sync even if Steam build has not changed")
    parser.add_argument("--dry-run", action="store_true", help="Check and report differences without writing files")
    parser.add_argument("--rust-dir", type=Path, default=DEFAULT_RUST_DIR, help="Path to Rust Bundles/items directory")
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS_DIR, help="Path to industrial-hub-assets repo")
    args = parser.parse_args()

    rust_dir = args.rust_dir
    assets_dir = args.assets_dir
    items_dir = assets_dir / "items"
    manifest_path = assets_dir / "manifest.json"
    sync_state_path = assets_dir / "sync_state.json"
    acf_path = DEFAULT_STEAM_ACF

    print("==================================================")
    print(" 🛠️  Rust Asset Sync & Optimizer")
    print("==================================================")
    print(f"Rust Source:  {rust_dir}")
    print(f"Assets Repo:  {assets_dir}")
    print(f"Target Items: {items_dir}")

    if not rust_dir.exists():
        print(f"[Error] Rust source directory not found: {rust_dir}")
        sys.exit(1)
    if not items_dir.exists():
        print(f"[Error] Target items directory not found: {items_dir}")
        sys.exit(1)

    # 1. Check Steam Build status
    current_build_id, current_last_updated = get_steam_build_info(acf_path)
    sync_state = load_json(sync_state_path, default={
        "rustBuildId": None,
        "rustLastUpdated": None,
        "lastSyncedAt": None,
        "items": {}
    })
    previous_build_id = sync_state.get("rustBuildId")
    prev_items_state = sync_state.get("items", {})

    print(f"\n[1/5] Checking Steam status:")
    print(f"  Current Steam Build ID:  {current_build_id}")
    print(f"  Previous Synced Build:   {previous_build_id}")
    if current_last_updated:
        updated_dt = datetime.fromtimestamp(current_last_updated, tz=timezone.utc).isoformat()
        print(f"  Steam Last Updated UTC:  {updated_dt}")

    if current_build_id and previous_build_id and current_build_id == previous_build_id and not args.force:
        print("\n✅ Rust has not updated since last sync. Nothing to do!")
        print("   (Pass --force to scan and check hashes anyway).")
        return

    # 2. Scan Rust source files
    print("\n[2/5] Scanning Rust source files (512x512)...")
    rust_pngs = {p.name: p for p in rust_dir.glob("*.png")}
    print(f"  Found {len(rust_pngs)} PNG icons in Rust Bundles/items.")

    # 3. Load existing manifest.json
    manifest = load_json(manifest_path, default={
        "version": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "count": 0,
        "files": {}
    })
    manifest_files = manifest.get("files", {})

    # 4. Compare hashes and categorize
    print("\n[3/5] Comparing image hashes (source vs compressed)...")
    to_add = []
    to_update = []
    unchanged = []
    new_metadata = []

    # Map for space vs dot variants in existing assets (e.g. '2module car.png' vs '2module.car.png')
    existing_dest_files = {p.name: p for p in items_dir.glob("*.png")}

    for name, src_path in rust_pngs.items():
        src_hash = compute_sha256(src_path)
        src_size = src_path.stat().st_size

        # Check corresponding companion JSON for metadata
        companion_json = rust_dir / f"{src_path.stem}.json"
        meta = None
        if companion_json.exists():
            try:
                with open(companion_json, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                pass

        # Determine target file name: keep existing name if space-variant exists
        target_name = name
        if name not in existing_dest_files:
            space_variant = name.replace(".", " ").replace(" png", ".png")
            if space_variant in existing_dest_files:
                target_name = space_variant

        dest_file = items_dir / target_name
        dest_exists = dest_file.exists()

        stored_state = prev_items_state.get(target_name)

        if not dest_exists:
            to_add.append((target_name, src_path, src_hash, src_size, meta))
        elif stored_state and stored_state.get("sourceHash") == src_hash:
            # Source hash matches stored state -> unchanged
            unchanged.append(target_name)
        elif not stored_state and target_name in manifest_files:
            # Baseline entry: destination exists in manifest, initialize source hash
            # If destination already exists, we trust it until sourceHash changes in a future wipe
            unchanged.append(target_name)
            prev_items_state[target_name] = {
                "sourceHash": src_hash,
                "sourceSize": src_size,
                "compressedHash": manifest_files[target_name]["hash"],
                "compressedSize": manifest_files[target_name]["size"],
                "updatedAt": manifest.get("updatedAt")
            }
        else:
            # Source hash differs from stored state or missing state -> item updated
            to_update.append((target_name, src_path, src_hash, src_size, meta))

    print(f"  Summary:")
    print(f"    - Unchanged: {len(unchanged)}")
    print(f"    - To Add:    {len(to_add)}")
    print(f"    - To Update: {len(to_update)}")

    if to_add:
        print(f"\n  Sample new items to add (first 10):")
        for item in to_add[:10]:
            print(f"    + {item[0]}")

    if to_update:
        print(f"\n  Sample items to update (first 10):")
        for item in to_update[:10]:
            print(f"    ~ {item[0]}")

    if args.dry_run:
        print("\n🔍 Dry-run completed. No files were written.")
        return

    if not to_add and not to_update and len(prev_items_state) == len(manifest_files):
        print("\n✅ All items are completely up to date with Rust.")
        # Just update build ID in sync_state if needed
        sync_state["rustBuildId"] = current_build_id
        sync_state["rustLastUpdated"] = current_last_updated
        sync_state["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
        save_json(sync_state_path, sync_state)
        return

    # 5. Process and resize new/modified items
    print("\n[4/5] Resizing (512x512 -> 128x128 Lanczos) and saving...")
    all_work = to_add + to_update
    processed_count = 0

    for target_name, src_path, src_hash, src_size, meta in all_work:
        dest_path = items_dir / target_name
        resize_and_optimize(src_path, dest_path)

        comp_hash = compute_sha256(dest_path)
        comp_size = dest_path.stat().st_size
        now_iso = datetime.now(timezone.utc).isoformat()

        # Update manifest
        manifest_files[target_name] = {
            "hash": comp_hash,
            "size": comp_size
        }

        # Update sync_state with both hashes
        prev_items_state[target_name] = {
            "sourceHash": src_hash,
            "sourceSize": src_size,
            "compressedHash": comp_hash,
            "compressedSize": comp_size,
            "updatedAt": now_iso
        }

        if meta:
            new_metadata.append(meta)

        processed_count += 1
        if processed_count % 50 == 0 or processed_count == len(all_work):
            print(f"  Progress: {processed_count}/{len(all_work)} processed...")

    # 6. Save manifest.json & sync_state.json
    print("\n[5/5] Saving manifest.json and sync_state.json...")
    manifest["count"] = len(manifest_files)
    manifest["updatedAt"] = datetime.now(timezone.utc).isoformat()
    manifest["files"] = dict(sorted(manifest_files.items()))
    save_json(manifest_path, manifest)

    sync_state["rustBuildId"] = current_build_id
    sync_state["rustLastUpdated"] = current_last_updated
    sync_state["lastSyncedAt"] = datetime.now(timezone.utc).isoformat()
    sync_state["items"] = dict(sorted(prev_items_state.items()))
    save_json(sync_state_path, sync_state)

    print(f"\n🎉 Successfully synchronized Rust assets!")
    print(f"   Manifest total assets: {manifest['count']}")
    print(f"   New items added:       {len(to_add)}")
    print(f"   Items updated:         {len(to_update)}")

    # Save new metadata report if any new items were added
    if new_metadata:
        report_path = assets_dir / "latest_sync_new_items.json"
        save_json(report_path, new_metadata)
        print(f"   New items metadata saved to: {report_path.name}")

    print("\nNext step: review and commit changes to git:")
    print("   cd C:\\Users\\dimav\\source\\repos\\industrial-hub-assets")
    print("   git add .")
    print(f'   git commit -m "Sync Rust update (Build {current_build_id})"')
    print("   git push origin main")

if __name__ == "__main__":
    main()
