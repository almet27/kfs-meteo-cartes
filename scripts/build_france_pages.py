#!/usr/bin/env python3
"""Build a size-capped GitHub Pages snapshot from genuine KFS France artifacts.

No generated PNGs are committed to Git history. No synthetic steps or fields.
Run with --allow-partial to preview smoke-test artifacts.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from PIL import Image

MODELS = {"ifs": 3, "aifs-single": 6, "gfs": 3, "aigfs": 6}
REQUIRED = {"t2m", "t850", "wind10m", "mslp", "precip_total"}


def parse_time(s):
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def valid_manifest(data, allow_partial=False):
    model = data.get("model")
    if model not in MODELS or data.get("area") != "France":
        return False
    steps = data.get("requested_steps_h", [])
    maps = data.get("maps", {})
    expected = list(range(MODELS[model], 73, MODELS[model]))
    if not steps or not all(
        isinstance(s, int) and s % MODELS[model] == 0 and 0 < s <= 72 for s in steps
    ):
        return False
    if not allow_partial and steps != expected:
        return False
    for step in steps:
        available = maps.get(str(step), {})
        if not isinstance(available, dict) or not REQUIRED.issubset(available):
            return False
        for metric in REQUIRED:
            entry = available[metric]
            if not isinstance(entry, dict) or not str(entry.get("path", "")).endswith(".png"):
                return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("/tmp/kfs-pages"))
    parser.add_argument("--include-existing", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--max-megabytes", type=int, default=450)
    parser.add_argument("--require-all-models", action="store_true")
    parser.add_argument("--require-latest", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    if args.include_existing:
        for folder in ("forecast-maps/europe", "forecast-maps/tendance",
                       "radar", "rainviewer", "cartes"):
            source = Path(folder)
            if source.is_dir():
                shutil.copytree(source, args.output / folder, dirs_exist_ok=True)
    (args.output / ".nojekyll").touch()
    candidates = {}
    for meta in args.artifacts.rglob("metadata.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            if not valid_manifest(data, args.allow_partial):
                continue
            model = data["model"]
            key = (parse_time(data["run_utc"]), parse_time(data["generated_utc"]))
            if model not in candidates or key > candidates[model][0]:
                candidates[model] = (key, meta, data)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    if not candidates:
        raise SystemExit("No valid France atlas; refusing to deploy incomplete Pages site")
    if args.require_all_models and set(candidates) != set(MODELS):
        raise SystemExit("Incomplete model set, refusing deployment: " + repr(sorted(candidates)))
    if args.require_latest:
        latest = json.loads(Path("forecast-maps/france/latest-cycles.json").read_text(encoding="utf-8"))["models"]
        for model, (_, _, source) in candidates.items():
            expected = latest.get(model, {}).get("latest_72h_temperature_step_utc")
            if not expected or parse_time(source["run_utc"]) != parse_time(expected):
                raise SystemExit("Stale atlas for " + model + ", expected: " + str(expected))
    models = {}
    for model, (_, metadata_path, source) in sorted(candidates.items()):
        out = args.output / "forecast-maps/france" / model
        out.mkdir(parents=True, exist_ok=True)
        new_maps = {}
        for step, fields in sorted(source["maps"].items(), key=lambda x: int(x[0])):
            new_maps[step] = {}
            for metric, old in fields.items():
                name = Path(old.get("path", "")).name
                if not name.endswith(".png"):
                    continue
                filename = metadata_path.parent / name
                if not filename.is_file():
                    if metric in REQUIRED:
                        raise SystemExit("Missing required forecast image: " + str(filename))
                    continue
                target = out / (filename.stem + ".webp")
                with Image.open(filename) as image:
                    if image.width < 350 or image.height < 250:
                        raise SystemExit("Unusually small image: " + str(filename))
                    image.convert("RGB").save(target, "WEBP", quality=89, method=6)
                new_maps[step][metric] = {
                    "path": str(target.relative_to(args.output)),
                    "note": str(old.get("note", "")),
                    "content_type": "image/webp",
                }
        models[model] = {
            "model_name": source.get("model_name", model),
            "run_utc": source["run_utc"],
            "generated_utc": source["generated_utc"],
            "native_step_h": source["native_step_h"],
            "requested_steps_h": source["requested_steps_h"],
            "complete_72h": not args.allow_partial,
            "maps": new_maps,
            "errors": source.get("errors", {}),
        }
    manifest = {
        "schema": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "area": "France",
        "models": models,
        "notes": [
            "Only actual source model runs and native steps; never interpolated.",
            "Snow is water equivalent, not snow depth.",
            "GFS phase estimates labelled, AIGFS may provide total precipitation only.",
        ],
    }
    folder = args.output / "forecast-maps/france"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "metadata.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    total = sum(file.stat().st_size for file in args.output.rglob("*") if file.is_file())
    if total > args.max_megabytes * 1_000_000:
        raise SystemExit(
            "Pages site exceeds budget: %.1f MB > %s MB" %
            (total / 1e6, args.max_megabytes)
        )
    images = sum(1 for file in args.output.rglob("*.webp"))
    print(json.dumps({
        "models": list(models),
        "images": images,
        "size_megabytes": round(total / 1e6, 2),
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
