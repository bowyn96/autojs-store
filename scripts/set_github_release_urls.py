#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 plugins/projects 下 meta.json（及 index.json）的下载地址写成 GitHub Release URL。

URL 规则（可改 --plugin-tag / --project-tag）：
  插件: https://github.com/{owner}/{repo}/releases/download/plugin-{id}-{version}/{asset}
  项目: https://github.com/{owner}/{repo}/releases/download/projects-v1/{asset}

asset 优先用目录内 .apk/.zip；否则用 meta.release_asset。

示例：
  # 只预览
  python3 scripts/set_github_release_urls.py --owner bowyn96 --repo autojs-store --dry-run

  # 写回 meta + index
  python3 scripts/set_github_release_urls.py --owner bowyn96 --repo autojs-store --write

  # 顺带用 gh 把本地包上传到对应 Release（需已 gh auth）
  python3 scripts/set_github_release_urls.py --owner bowyn96 --repo autojs-store --write --upload
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

STORE_ROOT = Path(__file__).resolve().parents[1]


def safe_seg(s: str) -> str:
    """Release tag / 文件名安全片段（与历史上传命名一致）。"""
    s = re.sub(r"[^\w.\-]+", "_", str(s).strip())
    return (s[:80] or "x").strip("._")


def find_package(folder: Path) -> Path | None:
    cands = [
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in (".apk", ".zip", ".aab")
    ]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_size)


def release_url(owner: str, repo: str, tag: str, asset: str) -> str:
    return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{asset}"


def load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict | list) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def gh_upload(owner: str, repo: str, tag: str, asset_path: Path, title: str) -> None:
    remote = f"{owner}/{repo}"
    # 若 Release 不存在则创建
    view = subprocess.run(
        ["gh", "release", "view", tag, "-R", remote],
        capture_output=True,
        text=True,
    )
    if view.returncode != 0:
        subprocess.check_call(
            [
                "gh",
                "release",
                "create",
                tag,
                str(asset_path),
                "-R",
                remote,
                "--title",
                title,
                "--notes",
                f"asset: {asset_path.name}",
            ]
        )
    else:
        subprocess.check_call(
            [
                "gh",
                "release",
                "upload",
                tag,
                str(asset_path),
                "-R",
                remote,
                "--clobber",
            ]
        )


def process_plugins(
    owner: str,
    repo: str,
    tag_tpl: str,
    write: bool,
    upload: bool,
) -> list[dict]:
    root = STORE_ROOT / "plugins"
    index_path = root / "index.json"
    index = load_json(index_path)
    by_id = {str(x.get("id")): x for x in index}
    rows = []

    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        meta_path = folder / "meta.json"
        if not meta_path.is_file():
            continue
        meta = load_json(meta_path)
        pid = str(meta.get("id") or "")
        pkg = meta.get("package_name") or folder.name
        ver = meta.get("version") or "0"
        pkg_file = find_package(folder)
        asset = pkg_file.name if pkg_file else (meta.get("release_asset") or "")
        if not asset:
            print(f"[skip] plugin {folder.name}: no package", file=sys.stderr)
            continue
        tag = tag_tpl.format(id=pid, version=safe_seg(ver), package=safe_seg(pkg))
        url = release_url(owner, repo, tag, asset)
        rows.append(
            {
                "kind": "plugin",
                "folder": folder.name,
                "tag": tag,
                "asset": asset,
                "url": url,
                "path": str(pkg_file) if pkg_file else "",
                "title": f"{meta.get('name') or pkg} {ver}",
            }
        )
        if write:
            meta["fileUrl"] = url
            meta["file"] = url
            meta["url"] = url
            meta["release_asset"] = asset
            meta["release_tag"] = tag
            dump_json(meta_path, meta)
            if pid in by_id:
                item = by_id[pid]
                item["fileUrl"] = url
                item["file"] = url
                item["url"] = url
        if upload and pkg_file:
            gh_upload(owner, repo, tag, pkg_file, rows[-1]["title"])

    if write:
        dump_json(index_path, index)
    return rows


def process_projects(
    owner: str,
    repo: str,
    tag_tpl: str,
    write: bool,
    upload: bool,
) -> list[dict]:
    root = STORE_ROOT / "projects"
    index_path = root / "index.json"
    index = load_json(index_path)
    by_id = {str(x.get("id")): x for x in index}
    rows = []
    upload_files: list[tuple[str, Path, str]] = []

    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        meta_path = folder / "meta.json"
        if not meta_path.is_file():
            continue
        meta = load_json(meta_path)
        pid = str(meta.get("id") or "")
        pkg = meta.get("packageName") or folder.name
        ver = meta.get("version") or "0"
        pkg_file = find_package(folder)
        asset = pkg_file.name if pkg_file else (meta.get("release_asset") or "")
        if not asset:
            print(f"[skip] project {folder.name}: no package", file=sys.stderr)
            continue
        tag = tag_tpl.format(id=pid, version=safe_seg(ver), package=safe_seg(pkg))
        url = release_url(owner, repo, tag, asset)
        rows.append(
            {
                "kind": "project",
                "folder": folder.name,
                "tag": tag,
                "asset": asset,
                "url": url,
                "path": str(pkg_file) if pkg_file else "",
                "title": f"{meta.get('name') or pkg} {ver}",
            }
        )
        if write:
            meta["fileUrl"] = url
            meta["file"] = url
            meta["release_asset"] = asset
            meta["release_tag"] = tag
            dump_json(meta_path, meta)
            if pid in by_id:
                item = by_id[pid]
                item["fileUrl"] = url
                item["file"] = url
        if upload and pkg_file:
            upload_files.append((tag, pkg_file, rows[-1]["title"]))

    if write:
        dump_json(index_path, index)

    if upload and upload_files:
        # 若 tag 模板是固定 projects-v1，批量挂到同一个 Release
        by_tag: dict[str, list[tuple[Path, str]]] = {}
        for tag, path, title in upload_files:
            by_tag.setdefault(tag, []).append((path, title))
        remote = f"{owner}/{repo}"
        for tag, files in by_tag.items():
            view = subprocess.run(
                ["gh", "release", "view", tag, "-R", remote],
                capture_output=True,
                text=True,
            )
            paths = [str(p) for p, _ in files]
            if view.returncode != 0:
                subprocess.check_call(
                    [
                        "gh",
                        "release",
                        "create",
                        tag,
                        *paths,
                        "-R",
                        remote,
                        "--title",
                        f"Projects {tag}",
                        "--notes",
                        f"{len(paths)} project packages",
                    ]
                )
            else:
                for p in paths:
                    subprocess.check_call(
                        ["gh", "release", "upload", tag, p, "-R", remote, "--clobber"]
                    )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Set meta/index fileUrl to GitHub Release links")
    ap.add_argument("--owner", default="bowyn96")
    ap.add_argument("--repo", default="autojs-store")
    ap.add_argument(
        "--plugin-tag",
        default="plugin-{id}-{version}",
        help="插件 Release tag 模板，可用 {id} {version} {package}",
    )
    ap.add_argument(
        "--project-tag",
        default="projects-v1",
        help="项目 Release tag 模板；默认共用 projects-v1",
    )
    ap.add_argument("--plugins-only", action="store_true")
    ap.add_argument("--projects-only", action="store_true")
    ap.add_argument("--write", action="store_true", help="写回 meta.json 与 index.json")
    ap.add_argument("--upload", action="store_true", help="gh release 上传本地包")
    ap.add_argument("--dry-run", action="store_true", help="仅打印（默认也是只打印，除非 --write）")
    args = ap.parse_args()

    do_plugins = not args.projects_only
    do_projects = not args.plugins_only
    write = bool(args.write) and not args.dry_run

    rows: list[dict] = []
    if do_plugins:
        rows += process_plugins(args.owner, args.repo, args.plugin_tag, write, args.upload and write)
    if do_projects:
        rows += process_projects(args.owner, args.repo, args.project_tag, write, args.upload and write)

    for r in rows:
        print(f"{r['kind']:7} {r['folder']}: {r['url']}")
    print(f"# total {len(rows)}  write={write} upload={args.upload and write}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
