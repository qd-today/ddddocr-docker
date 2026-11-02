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

# 默认启用原生 arm64 runner，与 pycurl-docker 的判定一致（那里是 != "false"）。
# 原来写的是 == "true"，而没有任何地方传 NATIVE_ARM，等于 arm 构建一直跑在 x86_64 上
# 靠 QEMU 模拟。要临时退回 QEMU 时设 NATIVE_ARM=false。
arm_runner = (
    "ubuntu-latest"
    if os.environ.get("NATIVE_ARM") == "false"
    else "ubuntu-24.04-arm"
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


def dddocr_version() -> str:
    """镜像 tag 与 wheel 版本断言都用它，只有一个来源：

    * tag 推送 -> tag 名（发布 1.6.2 就是 1.6.2，不会因为输入默认值写成 1.6.1）
    * workflow_dispatch -> 输入（默认 1.6.1）
    """
    if os.environ.get("REF", "").startswith("refs/tags/"):
        return os.environ["REF_NAME"]
    return (os.environ.get("DDDDOCR_VERSION_INPUT") or "").strip() or "1.6.1"


def wheel_entry(platform: str) -> dict:
    """第一段：编 wheel，跑在编译最快的 runner 上。

    arm 系列都放原生 arm64 —— armv7 在那儿由内核 compat 模式执行，编 wheel 没问题
    （wheel 的 tag 由 setuptools/auditwheel 按 gcc target 生成，是 armv7l；Python 自报
    aarch64 只影响运行时判断）。但**装** wheel 不能在那儿做：compat 模式下 Python 自报
    linux-aarch64，uv 会挂死（pycurl-docker 实测过，x86_64 上两版 uv 都 1-2 秒通过、
    arm64 runner 上两版都超时）。所以安装统一放到第二段的 x86_64 上。
    """
    return {
        "platform": platform,
        "group": platform.replace("linux/", "").replace("/", "-"),
        "arch": arch_map[platform],
        "runner": arm_runner if platform == "linux/arm64" else "ubuntu-latest",
        "base_image": base_of(platform),
    }


def runtime_entry(platform: str) -> dict:
    """第二段：用第一段的产物组装 wheelhouse 与 runtime，统一跑 x86_64。"""
    e = wheel_entry(platform)
    e["runner"] = "ubuntu-latest"
    return e


wheel_matrix = [wheel_entry(p) for p in plats]
runtime_matrix = [runtime_entry(p) for p in plats]

print("wheel_matrix=" + json.dumps({"include": wheel_matrix}))
print("runtime_matrix=" + json.dumps({"include": runtime_matrix}))
print("smoke_matrix=" + json.dumps({"include": wheel_matrix}))
print("expected=" + ",".join(sorted(plats)))
print("full=%s" % str(sorted(plats) == sorted(default)).lower())
print("ddddocr_ref=" + dddocr_ref())
print("version=" + dddocr_version())
