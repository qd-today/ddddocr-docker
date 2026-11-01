#!/usr/bin/env python3
"""校验 README 里写的版本号与 Dockerfile 的 ARG 默认值一致。

版本号真正的源头只有一处：Dockerfile 的 ``ARG X_VERSION=``（构建时生效的就是它）。
README 里出现的是它的副本，改了 ARG 忘了改文档，由这个脚本拦下——在 CI 的 plan
阶段就跑，失败发生在构建之前。

校验三处：

1. 版本参数表：``| `pycurl_version` | 说明 | 7.48.0 |`` 的最后一列必须等于 ARG 值
2. 镜像内容表：``| curl | 8.23.0（自编） | ... |`` 里的版本号必须等于 ARG 值
3. 代码块里的 ``FROM alpine:3.24`` 里的 alpine 版本必须等于 ``ALPINE_VERSION``

用法::

    python3 check_versions.py            # 校验，不一致则退出码 1
    python3 check_versions.py --print    # 顺带打印解析到的版本表
"""

import re
import sys
from pathlib import Path

# README 里的组件名 → Dockerfile 的 ARG 名
COMPONENT_ARGS = {
    "pycurl": "PYCURL_VERSION",
    "curl": "CURL_VERSION",
    "ngtcp2": "NGTCP2_VERSION",
    "nghttp3": "NGHTTP3_VERSION",
    "opencv": "OPENCV_VERSION",
    "pillow": "PILLOW_VERSION",
    "numpy": "NUMPY_VERSION",
    "onnxruntime": "ONNX_VERSION",
    "python": None,  # Python 版本由 alpine 决定，不是独立参数
}

VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)*")
ARG_RE = re.compile(r"^ARG ([A-Z0-9_]*VERSION)=(\S*)", re.M)


def dockerfile_args(repo: Path) -> dict[str, str]:
    """取所有 Dockerfile 里的 ARG 默认值；同名 ARG 取值不一致直接报错。"""
    args: dict[str, str] = {}
    for df in sorted(repo.glob("Dockerfile*")):
        for name, value in ARG_RE.findall(df.read_text(encoding="utf-8")):
            value = value.strip("\"'")
            if name in args and args[name] != value:
                raise SystemExit(
                    f"错误: {df.name} 里 {name}={value}，与其它 Dockerfile 的 "
                    f"{args[name]} 不一致——同一个参数只能有一个默认值"
                )
            args[name] = value
    return args


def check(repo: Path) -> list[str]:
    args = dockerfile_args(repo)
    if not args:
        raise SystemExit(f"错误: {repo} 下没有 Dockerfile，找不到版本号源头")
    readme = repo / "README.md"
    if not readme.is_file():
        return []
    text = readme.read_text(encoding="utf-8")
    problems: list[str] = []

    # 1) 版本参数表：| `xxx_version` | 说明 | 版本 |
    for line in text.splitlines():
        m = re.match(r"^\|\s*`([a-z0-9_]+_version)`\s*\|(.*)$", line)
        if not m:
            continue
        param, rest = m.group(1), m.group(2)
        cells = [c.strip() for c in rest.rstrip().rstrip("|").split("|")]
        if not cells:
            continue
        declared = cells[-1]
        arg = param.upper()
        if arg not in args:
            problems.append(f"README 里参数 `{param}` 在 Dockerfile 里没有对应的 ARG")
            continue
        if args[arg] and declared != args[arg]:
            problems.append(
                f"README 版本参数表: `{param}` 写的是 {declared}，Dockerfile 里是 {args[arg]}"
            )

    # 2) 镜像内容表：| 组件 | 版本 | ...
    for line in text.splitlines():
        m = re.match(r"^\|\s*([A-Za-z0-9_ +]+?)\s*\|(.*)$", line)
        if not m:
            continue
        component, rest = m.group(1).strip(), m.group(2)
        key = component.lower()
        if key not in COMPONENT_ARGS or COMPONENT_ARGS[key] is None:
            continue
        arg = COMPONENT_ARGS[key]
        if arg not in args or not args[arg]:
            continue
        cell = rest.split("|")[0].strip()
        # 体积单元格（24.4 MB）不是版本号，跳过
        if re.search(r"\b(MB|MiB|KB|GB|MiB)\b", cell):
            continue
        found = VERSION_RE.search(cell)
        if found and found.group(0) != args[arg]:
            problems.append(
                f"README 镜像内容表: `{component}` 写的是 {found.group(0)}，"
                f"Dockerfile 里 {arg}={args[arg]}"
            )

    # 3) 代码块里的 FROM alpine:X.Y
    alpine = args.get("ALPINE_VERSION", "")
    if alpine:
        for m in re.finditer(r"FROM alpine:(\d+\.\d+)", text):
            if m.group(1) != alpine:
                problems.append(
                    f"README 代码块: FROM alpine:{m.group(1)}，Dockerfile 里 "
                    f"ALPINE_VERSION={alpine}"
                )

    return problems


def main() -> int:
    # scripts/check_versions.py -> .github/workflows/scripts -> .github/workflows
    # -> .github -> 仓库根
    repo = Path(__file__).resolve().parents[3]
    if "--print" in sys.argv:
        args = dockerfile_args(repo)
        for k in sorted(args):
            print(f"  {k}={args[k]}")
    problems = check(repo)
    if problems:
        print("版本号与 Dockerfile 不一致：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("版本号与 Dockerfile 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
