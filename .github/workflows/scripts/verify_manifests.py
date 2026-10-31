#!/usr/bin/env python3
"""合并后回读 manifest，按集合比对平台是否与预期一致。

digest 数量对不等于 manifest 里平台对（同一平台被合并两次、另一平台被吞掉的情况出现
过），所以用集合而不是数量。
"""

import json
import os
import subprocess
import sys

expected = {p.strip() for p in os.environ["EXPECTED"].split(",") if p.strip()}
image = os.environ["IMAGE"]


def platforms(tag: str) -> set[str]:
    try:
        raw = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", "--raw", tag],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "::error::无法读取 %s 的 manifest: %s"
            % (tag, (exc.stderr or "").strip()[:300])
        )
    index = json.loads(raw)
    out = set()
    for entry in index.get("manifests", []):
        p = entry.get("platform") or {}
        arch = p.get("architecture")
        if not arch or arch == "unknown":
            continue
        variant = p.get("variant")
        out.add(
            "%s/%s%s"
            % (p.get("os", "linux"), arch, "/" + variant if variant else "")
        )
    return out


failed = False
for tag in os.environ["TAGS"].split():
    full = "%s:%s" % (image, tag)
    got = platforms(full)
    if got == expected:
        print("OK   %s -> %d 平台" % (tag, len(got)))
        continue
    failed = True
    print("FAIL %s" % full)
    print("     缺失: %s" % (sorted(expected - got) or "无"))
    print("     多余: %s" % (sorted(got - expected) or "无"))
if failed:
    sys.exit("::error::manifest 平台完整性校验失败")
