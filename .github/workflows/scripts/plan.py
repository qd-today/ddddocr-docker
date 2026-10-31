#!/usr/bin/env python3
"""计算构建矩阵，输出到 stdout（key=value 形式，由 workflow 追加到 $GITHUB_OUTPUT）。

从环境变量读取输入，只读仓库里的 ddddocr.version（tag 发布时的 commit pin）。
"""

import json
import os
import sys
from pathlib import Path

default = [p.strip() for p in os.environ["DEFAULT_PLATFORMS"].split(",") if p.strip()]
raw = (os.environ.get("PLATFORM_INPUT") or "").strip()
plats = [p.strip() for p in raw.split(",") if p.strip()] if raw else default

# 可用平台 = 实测通过的 6 个（全部具备完整 OCR 栈）。加新平台前先确认：
#   1) 该架构能编 OpenCV / Pillow，且 a76yyyy/onnxruntime:<ver>-wheelhouse 里有同架构
#      的 onnxruntime 与 numpy wheel；
#   2) tests/smoke.py 的 ELF_MACHINE 里有它的 e_machine 编码。
allowed = {
    "linux/amd64",
    "linux/arm64",
    "linux/arm/v7",
    "linux/ppc64le",
    "linux/riscv64",
    "linux/loong64",
}
bad = [p for p in plats if p not in allowed]
if bad:
    sys.exit(
        "::error::不支持或未验证的平台: %s（可选: %s）"
        % (",".join(bad), ",".join(sorted(allowed)))
    )
dup = sorted({p for p in plats if plats.count(p) > 1})
if dup:
    sys.exit("::error::平台重复: %s" % ",".join(dup))

arm_runner = (
    "ubuntu-24.04-arm" if os.environ.get("NATIVE_ARM") == "true" else "ubuntu-latest"
)

# wheel 文件名里的架构串（与 auditwheel 产出的 musllinux_1_2_<arch> 对齐）
arch_map = {
    "linux/amd64": "x86_64",
    "linux/arm64": "aarch64",
    "linux/arm/v7": "armv7l",
    "linux/ppc64le": "ppc64le",
    "linux/riscv64": "riscv64",
    "linux/loong64": "loongarch64",
}


def base_of(platform: str) -> str:
    """只有 loong64 需要换基座：alpine 官方没有该架构，ghcr.io/loong64/alpine 有同
    Alpine 版本。空字符串 = 用 Dockerfile 里的默认 ${BASE_IMAGE}=alpine:${ALPINE_VERSION}。"""
    if platform == "linux/loong64":
        return "%s:%s" % (os.environ["LOONG64_BASE"], os.environ["ALPINE"])
    return ""


def dddocr_ref() -> str:
    """tag 发布用 ddddocr.version 锁定的 commit（可复现），其余跟随输入（默认 master）。"""
    if os.environ.get("REF", "").startswith("refs/tags/"):
        return Path("ddddocr.version").read_text(encoding="utf-8").strip()
    return (os.environ.get("DDDDOCR_REF_INPUT") or "").strip() or "master"


def entry(platform: str) -> dict:
    """一个平台一个 job，一个 job 里连着构建两个出口（build 阶段共享，不重复编译）：
    单平台 push-by-digest 得到的是单平台 manifest digest，发布时按平台逐一合并，
    冒烟也能按 digest 取回同一份字节。"""
    return {
        "platform": platform,
        "group": platform.replace("linux/", "").replace("/", "-"),
        "arch": arch_map[platform],
        "runner": arm_runner if platform == "linux/arm64" else "ubuntu-latest",
        "base_image": base_of(platform),
    }


include = [entry(p) for p in plats]

print("matrix=" + json.dumps({"include": include}))
print("smoke_matrix=" + json.dumps({"include": include}))
print("expected=" + ",".join(sorted(plats)))
print("full=%s" % str(sorted(plats) == sorted(default)).lower())
print("ddddocr_ref=" + dddocr_ref())
