#!/usr/bin/env python3
"""从多平台 index 里取指定平台的 manifest digest。

用法：wheel_digest.py <image:tag> <linux/平台>
输出：该平台的 digest（一行）。找不到时以非零退出码结束。

为什么需要它：docker create --platform 在多平台 tag 上会自己挑一个镜像，
不保证是请求的那个（CI 上实测 aarch64 拿到过 armv7l 的镜像）。按 digest
拉取才能确定拿到的是哪一份。
"""
import json
import subprocess
import sys


def main():
    if len(sys.argv) != 3:
        sys.exit("用法: wheel_digest.py <image:tag> <linux/平台>")
    image, plat = sys.argv[1], sys.argv[2]

    raw = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", image, "--raw"],
        capture_output=True, text=True, check=True,
    ).stdout
    for m in json.loads(raw).get("manifests", []):
        p = m.get("platform") or {}
        arch = "linux/" + p.get("architecture", "")
        if p.get("variant"):
            arch += "/" + p["variant"]
        if arch == plat:
            print(m["digest"])
            return 0
    sys.exit(f"::error::index 里没有 {plat}")


if __name__ == "__main__":
    sys.exit(main())
