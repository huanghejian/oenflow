#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_pipeline.py - V7.3 从 A阶段导演 JSON 一键完成：
空间校验 -> 语义安全打包 -> 逻辑素材能力路由 -> Prompt编译 -> 最终验收。

不要求真实图片/视频/音频 URL/file_id。真实文件绑定属于后续 video executor。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    print("\n$", " ".join(f'"{x}"' if " " in x else x for x in cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run V7.3 cut-take short-drama pipeline with ordinary image references")
    ap.add_argument("director_json", help="A-stage director JSON")
    ap.add_argument("--output-dir", default="output", help="Output directory")
    ap.add_argument("--tier", choices=["low", "medium", "high"], default=None, help="Override routing tier")
    ap.add_argument("--target-resolution", default="720P", choices=["480P", "720P", "1080P", "2K", "4K"])
    ap.add_argument("--model-config", default=None, help="model_registry.json; default: resources/model_registry.json")
    ap.add_argument("--asset-catalog", default=None, help="可选逻辑 asset_catalog JSON；默认从A阶段JSON读取")
    ap.add_argument("--pack-mode", choices=["balanced", "max_safe", "preferred_only"], default="balanced")
    ap.add_argument("--min-unit-duration", type=int, default=4)
    ap.add_argument("--target-duration", type=int, default=15)
    ap.add_argument("--max-duration", type=int, default=30)
    ap.add_argument("--no-cross-group", action="store_true")
    ap.add_argument("--keep-routing-debug", action="store_true")
    ap.add_argument("--allow-legacy-spatial", action="store_true", help="兼容旧A JSON：允许缺少 spatial_bible/spatial_plan")
    ap.add_argument("--max-spatial-cut-risk", choices=["low", "medium", "high"], default="medium")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    spatial_validator = here / "spatial_validator.py"
    packer = here / "shot_packer.py"
    router = here / "video_router.py"
    compiler = here / "prompt_compiler.py"
    validator = here / "validate_final.py"
    for p in (spatial_validator, packer, router, compiler, validator):
        if not p.exists():
            print(f"ERROR: missing script: {p}")
            return 2

    director = Path(args.director_json).resolve()
    if not director.exists():
        print(f"ERROR: director JSON not found: {director}")
        return 2

    outdir = Path(args.output_dir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    base = director.stem
    if base.endswith("_A导演输出"):
        base = base[:-len("_A导演输出")]
    elif base.endswith("_A_director"):
        base = base[:-len("_A_director")]

    spatial_enriched = outdir / f"{base}_A_spatial_enriched.json"
    spatial_report = outdir / f"{base}_spatial_validation.json"
    packed = outdir / f"{base}_generation_units.json"
    routed = outdir / f"{base}_routed_units.json"
    final = outdir / f"{base}_final_video_shots.json"
    report = outdir / f"{base}_validation.json"
    config = Path(args.model_config).resolve() if args.model_config else here.parent / "resources" / "model_registry.json"

    spatial_cmd = [
        sys.executable, str(spatial_validator), str(director), str(spatial_enriched),
        "--report", str(spatial_report),
    ]
    if args.allow_legacy_spatial:
        spatial_cmd.append("--allow-legacy")
    run(spatial_cmd)

    pack_cmd = [
        sys.executable, str(packer), str(spatial_enriched), str(packed),
        "--mode", args.pack_mode,
        "--min-unit-duration", str(args.min_unit_duration),
        "--target-duration", str(args.target_duration),
        "--max-duration", str(args.max_duration),
        "--max-spatial-cut-risk", args.max_spatial_cut_risk,
    ]
    if args.no_cross_group:
        pack_cmd.append("--no-cross-group")
    run(pack_cmd)

    route_cmd = [
        sys.executable, str(router), str(packed), str(routed),
        "--target-resolution", args.target_resolution,
        "--model-config", str(config),
    ]
    if args.asset_catalog:
        route_cmd.extend(["--asset-catalog", str(Path(args.asset_catalog).resolve())])
    if args.tier:
        route_cmd.extend(["--tier", args.tier])
    run(route_cmd)

    compile_cmd = [sys.executable, str(compiler), str(routed), str(final)]
    if args.keep_routing_debug:
        compile_cmd.append("--keep-routing-debug")
    run(compile_cmd)

    validate_cmd = [
        sys.executable, str(validator), str(final),
        "--model-config", str(config),
        "--report", str(report),
    ]
    if args.keep_routing_debug:
        validate_cmd.append("--allow-debug")
    run(validate_cmd)

    print("\nPIPELINE OK")
    print(f"spatial:  {spatial_enriched}")
    print(f"spatial validation: {spatial_report}")
    print(f"packed:   {packed}")
    print(f"routed:   {routed}")
    print(f"final:    {final}")
    print(f"validate: {report}")
    print("references: logical_only (真实文件由后续 video executor 绑定)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
