#!/usr/bin/env python3
"""把 ddddocr 运行栈打成「自包含 musllinux wheel」，并生成 PEP 503 索引。

四个入口，产物都落在 ``--out-dir``（Dockerfile 里是 ``/wheels``）：

* ``--opencv PREFIX``  自编 OpenCV 的安装前缀（cmake 的 ``-DCMAKE_INSTALL_PREFIX``）。
  组装成顶层 ``cv2`` 扩展后交 ``auditwheel repair``：``libopencv_*`` 与 libjpeg / libpng /
  libwebp 全部收进 ``opencv.libs/`` 并改写 RPATH，标签改成 ``musllinux_1_2_<arch>``。
* ``--repair WHEEL``   pip 直接打出来的 wheel（Pillow），只做 auditwheel 修复。
* ``--ddddocr SRC``    ddddocr 源码目录 -> 纯 python wheel（86MB 模型文件在包内）。
* ``--emit-index``     为 ``--out-dir`` 里已有的 wheel 生成 ``simple/``。

三处**只有本脚本能做**的事：

1. ``patchelf --set-rpath`` 指向 cmake 的 lib 目录。auditwheel 靠遍历 DT_NEEDED 定位库，
   而 ``libopencv_core.so.414`` 只在自编前缀里、不在 musl 的默认搜索路径上；先给它一条
   RPATH，auditwheel 后面会把这条 RPATH 改写成 ``$ORIGIN:$ORIGIN/opencv.libs`` 这类相对路径。

2. 把扩展模块放在 wheel 的**顶层**（``cv2.<EXT_SUFFIX>.so``），不是 ``cv2/`` 包里。
   OpenCV 的绑定在初始化时用写死的名字 ``cv2`` 注册子模块，并断言「子模块名必须以父模块
   名开头」；以 ``cv2.cv2`` 之名加载会直接抛
   ``Bindings generation error. Submodule name should always start with a parent module
   name. Parent name: cv2.cv2. Submodule name: cv2``。官方安装靠 ``cv2/__init__.py`` 把
   原生模块按顶层名 ``cv2`` 再 import 一次来规避；wheel 里不需要这层把戏，直接让扩展自己
   就是顶层的 ``cv2``（``__version__`` 由 C 代码写入，不依赖任何 py 文件）。

3. 改写 ddddocr wheel 的 ``Requires-Dist``：上游写死在 linux 上依赖
   ``opencv-python-headless``，而本仓库分发的是自编最小化 OpenCV（发行名 ``opencv``）。
   不改这一条，消费者装 ddddocr 时永远会去 PyPI 找 musllinux 版 opencv-python-headless
   ——那个不存在。只改这一行，其余依赖（numpy / onnxruntime / Pillow）原样保留。

打包期断言（构建失败而不是交给人工检查）：``opencv.libs/`` 必须含 libjpeg / libpng /
libwebp / libwebpmux / libwebpdemux；Pillow 的 ``_imaging*.so`` 不得链 libimagequant
（GPL-3.0）。
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

# opencv.libs/ 里必须有这些（缺一个说明 OpenCV 的编解码器没被自包含化）
CV2_REQUIRED_LIBS = ("libjpeg*", "libpng*", "libwebp*", "libwebpmux*", "libwebpdemux*")


def die(message: str) -> int:
    print(f"错误: {message}", file=sys.stderr)
    return 1


# --------------------------------------------------------------------------- #
# auditwheel
# --------------------------------------------------------------------------- #
def auditwheel_repair(raw_wheel: Path, out_dir: Path) -> Path:
    """让 auditwheel 收集 DT_NEEDED 闭包、改名入 ``<发行名>.libs/``、改 RPATH、重打标签。

    必须在**装了被解析库的构建镜像**里跑，否则报
    ``Cannot repair wheel, because required library "..." could not be located``。
    不传 ``--plat``：auditwheel 从 ELF interpreter 认出 musl，自己给出
    ``musllinux_1_2_<arch>``，所以对 6 个架构一视同仁。

    依赖目录名由 auditwheel 定死为「发行名 + .libs」（``repair.py`` 里
    ``dest_dir = wheel 名的 name 段 + lib_sdir``，``--lib-sdir`` 是**后缀**不是全名），
    所以 opencv wheel 里是 ``opencv.libs/``、Pillow 里是 ``pillow.libs/``。
    """
    before = {p.resolve() for p in out_dir.glob("*.whl")}
    subprocess.run(
        [
            sys.executable, "-m", "auditwheel", "repair",
            "--wheel-dir", str(out_dir),
            str(raw_wheel),
        ],
        check=True,
    )
    produced = sorted({p.resolve() for p in out_dir.glob("*.whl")} - before)
    if len(produced) != 1:
        raise SystemExit(f"错误: 期望 {out_dir} 里新增恰好 1 个 wheel, 实际 {produced}")
    return produced[0]


def wheel_entries(wheel: Path) -> list[tuple[str, int]]:
    with zipfile.ZipFile(wheel) as zf:
        return [(i.filename, i.file_size) for i in zf.infolist()]


def find_libs_dir(wheel: Path) -> str:
    """auditwheel 把依赖放在 ``<pkg>.libs/``（单顶层包时取包名，多顶层包时取发行名）。"""
    dirs = sorted({e[0].split("/")[0] for e in wheel_entries(wheel) if ".libs/" in e[0]})
    if len(dirs) != 1:
        raise SystemExit(f"错误: {wheel.name} 里找不到唯一的 .libs/ 目录（实际 {dirs}）")
    return dirs[0] + "/"


def assert_bundled(wheel: Path, patterns: tuple[str, ...]) -> list[str]:
    """打包期断言：``<pkg>.libs/`` 必须含这些库，缺了直接让构建失败。"""
    libs_dir = find_libs_dir(wheel)
    names = [
        e[0][len(libs_dir):]
        for e in wheel_entries(wheel)
        if e[0].startswith(libs_dir) and e[0] != libs_dir
    ]
    missing = [p for p in patterns if not any(fnmatch.fnmatch(n, p) for n in names)]
    if missing:
        raise SystemExit(
            f"错误: {wheel.name} 的 {libs_dir} 缺少 {missing}"
            f"（实际含: {sorted(names)}）—— 自包含化没生效，运行时 import 会失败"
        )
    return sorted(names)


def report(wheel: Path) -> None:
    """打印产物与 auditwheel 收进来的依赖（CI 日志里快速核对）。"""
    print(f"\n产物: {wheel.name}")
    print(f"大小: {wheel.stat().st_size / 1024 / 1024:.1f} MiB")
    entries = wheel_entries(wheel)
    libs_dir = find_libs_dir(wheel)
    bundled = sorted(
        (e for e in entries if e[0].startswith(libs_dir)), key=lambda e: -e[1]
    )
    print(f"{libs_dir} 库数量: {len(bundled)}")
    for name, size in bundled:
        print(f"  {name[len(libs_dir):]:44s} {size / 1024 / 1024:8.2f} MiB")
    own = sorted(
        (e for e in entries if not e[0].startswith(libs_dir)), key=lambda e: -e[1]
    )
    for name, size in own[:8]:
        if size >= 1024 * 1024:
            print(f"  {name:44s} {size / 1024 / 1024:8.2f} MiB")


def pack_tree(unroot: Path, dest_dir: Path) -> Path:
    """把组装好的 wheel 树打成 wheel，返回产物路径（调用方负责清理临时目录）。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    before = {p.resolve() for p in dest_dir.glob("*.whl")}
    subprocess.run(
        [sys.executable, "-m", "wheel", "pack", str(unroot), "--dest-dir", str(dest_dir)],
        check=True,
    )
    produced = sorted({p.resolve() for p in dest_dir.glob("*.whl")} - before)
    if len(produced) != 1:
        raise SystemExit(f"错误: 期望 {dest_dir} 里新增恰好 1 个 wheel, 实际 {produced}")
    return produced[0]


def write_dist_info(unroot: Path, name: str, version: str, summary: str, requires: list[str]) -> None:
    dist_info = unroot / f"{name}-{version}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    meta = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
        f"Summary: {summary}",
        "License: Apache-2.0",
    ]
    meta += [f"Requires-Dist: {r}" for r in requires]
    (dist_info / "METADATA").write_text("\n".join(meta) + "\n", encoding="utf-8")

    major, minor = sys.version_info[:2]
    plat = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    # 这里的 plat 只是「打包机的平台」，auditwheel 之后会改成 musllinux_1_2_<arch>
    (dist_info / "WHEEL").write_text(
        "Wheel-Version: 1.0\n"
        "Generator: ddddocr-docker pack_wheel.py\n"
        "Root-Is-Purelib: false\n"
        f"Tag: cp{major}{minor}-cp{major}{minor}-{plat}\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# OpenCV：cmake 安装树 -> cv2 wheel
# --------------------------------------------------------------------------- #
def find_cv2_module(prefix: Path) -> Path:
    """找 python 绑定的 .so（cmake 会放在 cv2/python-3.14/ 之类的子目录下）。"""
    found = sorted(
        p
        for p in prefix.rglob("cv2*.so")
        if p.is_file() and p.name.startswith("cv2")
    )
    if len(found) != 1:
        raise SystemExit(f"错误: 期望 {prefix} 里恰好 1 个 cv2 扩展, 实际 {found}")
    return found[0]


def find_opencv_libdir(prefix: Path) -> Path:
    """libopencv_core.so.* 所在目录（cmake 的 CMAKE_INSTALL_PREFIX/lib）。"""
    libs = sorted(prefix.rglob("libopencv_core.so*"))
    if not libs:
        raise SystemExit(f"错误: {prefix} 里找不到 libopencv_core.so*")
    return libs[0].parent


def build_opencv(prefix: Path, version: str, out_dir: Path) -> int:
    module = find_cv2_module(prefix)
    libdir = find_opencv_libdir(prefix)
    print(f"OpenCV 绑定: {module}")
    print(f"OpenCV 库目录: {libdir}")

    work = Path(tempfile.mkdtemp(prefix="cv2wheel-"))
    staging = Path(tempfile.mkdtemp(prefix="raw-"))
    try:
        unroot = work / "tree"
        unroot.mkdir()

        # 顶层模块，名字必须是 cv2.<EXT_SUFFIX>.so（见模块文档第 2 条）
        ext = sysconfig.get_config_var("EXT_SUFFIX")
        target = unroot / f"cv2{ext}"
        shutil.copyfile(module, target)
        shutil.copymode(module, target)

        # auditwheel 靠 RPATH 定位 libopencv_*（它们不在 musl 的默认搜索路径里）
        subprocess.run(["patchelf", "--set-rpath", str(libdir), str(target)], check=True)

        write_dist_info(
            unroot, "opencv", version,
            "OpenCV Python bindings (core/imgproc/imgcodecs), musllinux wheel",
            ["numpy"],
        )
        # 许可文件属于再分发时该带的内容，随 dist-info 走，不占顶层命名空间
        for extra in sorted(prefix.rglob("cv2/LICENSE*.txt")):
            licenses = unroot / f"opencv-{version}.dist-info" / "licenses"
            licenses.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(extra, licenses / extra.name)

        # 中间产物必须落在 out_dir 之外：CI 用 --output type=local 把整个目录取走，
        # 修复前的 linux_<arch> wheel 混进去会让下游的 *.whl 通配符装错文件
        raw = pack_tree(unroot, staging)
        wheel = auditwheel_repair(raw, out_dir)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)

    bundled = assert_bundled(wheel, CV2_REQUIRED_LIBS)
    report(wheel)
    print(f"断言通过: {find_libs_dir(wheel)} 含 {[n for n in bundled if n.startswith(('libjpeg', 'libpng', 'libwebp'))]}")
    return 0


# --------------------------------------------------------------------------- #
# Pillow：pip 打出来的 wheel -> auditwheel 修复
# --------------------------------------------------------------------------- #
def assert_no_imagequant(wheel: Path) -> None:
    """Pillow 不得链 libimagequant（GPL-3.0）。用 DT_NEEDED 判定：
    C 扩展里始终带着 HAVE_LIBIMAGEQUANT 这类配置字符串，用 strings 扫会误报。"""
    with zipfile.ZipFile(wheel) as zf:
        members = [n for n in zf.namelist() if n.startswith("PIL/") and n.endswith(".so")]
        if not members:
            raise SystemExit(f"错误: {wheel.name} 里没有 PIL/*.so")
        tmp = Path(tempfile.mkdtemp(prefix="pilcheck-"))
        try:
            for member in members:
                path = Path(zf.extract(member, tmp))
                out = subprocess.run(
                    ["readelf", "-d", str(path)], capture_output=True, text=True, check=True
                ).stdout
                if "imagequant" in out:
                    raise SystemExit(f"错误: {member} 的动态依赖里有 libimagequant（GPL-3.0）")
                if "libz.so" in out:
                    print(f"  {member}: 动态链接 libz（musllinux 白名单，由 system-packages.txt 提供）")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def repair_wheel(raw: Path, out_dir: Path) -> int:
    assert_no_imagequant(raw)
    wheel = auditwheel_repair(raw, out_dir)
    report(wheel)
    return 0


# --------------------------------------------------------------------------- #
# ddddocr：源码 -> 纯 python wheel（模型文件随之分发）
# --------------------------------------------------------------------------- #
OPENCV_REQ = re.compile(r"(?m)^Requires-Dist: opencv-python-headless\b")


def build_ddddocr(src: Path, out_dir: Path, expect_version: str) -> int:
    if not (src / "pyproject.toml").is_file():
        return die(f"{src} 里没有 pyproject.toml（不是 ddddocr 源码目录）")

    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="ddddocr-raw-"))
    work = Path(tempfile.mkdtemp(prefix="ddddocr-wheel-"))
    try:
        subprocess.run(
            [
                sys.executable, "-m", "pip", "wheel",
                "--no-deps", "--no-build-isolation", "--no-cache-dir",
                "--wheel-dir", str(staging), str(src),
            ],
            check=True,
        )
        raw = next(staging.glob("*.whl"))
        version = raw.name.split("-")[1]
        if expect_version and version != expect_version:
            raise SystemExit(
                f"错误: 源码里的 ddddocr 是 {version}，但期望 {expect_version}"
                f"（上游改了版本号？同步更新 DDDDOCR_VERSION）"
            )

        subprocess.run(
            [sys.executable, "-m", "wheel", "unpack", str(raw), "-d", str(work)], check=True
        )
        unroot = next(p for p in work.iterdir() if p.is_dir())

        # 上游把 linux 上的 OpenCV 依赖写死成 opencv-python-headless；本仓库分发的是
        # 自编最小化 OpenCV（发行名 opencv），不改这一行消费者装不上。
        metadata = next(unroot.glob("*.dist-info/METADATA"))
        text = metadata.read_text(encoding="utf-8")
        patched, count = OPENCV_REQ.subn("Requires-Dist: opencv", text)
        if count != 1:
            raise SystemExit(
                f"错误: {metadata.name} 里期望恰好 1 条 opencv-python-headless 依赖，实际 {count}"
                f"（上游依赖表变了？确认后同步本脚本）"
            )
        metadata.write_text(patched, encoding="utf-8")
        # wheel pack 会重算 RECORD，改完元数据不用手工修
        wheel = pack_tree(unroot, out_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)

    entries = wheel_entries(wheel)
    models = [e for e in entries if e[0].endswith(".onnx")]
    print(f"\n产物: {wheel.name}")
    print(f"大小: {wheel.stat().st_size / 1024 / 1024:.1f} MiB | 模型 {len(models)} 个")
    for line in patched.splitlines():
        if line.startswith("Requires-Dist:"):
            print(f"  {line}")
    return 0


# --------------------------------------------------------------------------- #
# PEP 503 索引
# --------------------------------------------------------------------------- #
def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def emit_index(root: Path) -> int:
    """为 root 下的 wheel 生成 PEP 503 索引，写入 root/simple/。

    链接用相对路径 ``../../<wheel>#sha256=...``，所以整个 wheelhouse 可以挂到任意
    目录，也可以多个 wheelhouse 各带一份索引由 ``--extra-index-url`` 叠加。
    重复执行会重建 simple/，不会残留上一次的项目目录。
    """
    wheels = sorted(root.glob("*.whl"))
    if not wheels:
        return die(f"{root} 下没有 .whl，无法生成索引")

    simple = root / "simple"
    if simple.exists():
        shutil.rmtree(simple)

    projects: dict[str, list[Path]] = {}
    for wheel in wheels:
        projects.setdefault(normalize_name(wheel.name.split("-")[0]), []).append(wheel)

    for name, files in sorted(projects.items()):
        page = simple / name
        page.mkdir(parents=True)
        links = "\n".join(
            f'    <a href="../../{w.name}#sha256={hashlib.sha256(w.read_bytes()).hexdigest()}">{w.name}</a><br/>'
            for w in files
        )
        (page / "index.html").write_text(
            f'<!DOCTYPE html>\n<html>\n  <head><meta charset="utf-8"/><title>{name}</title></head>\n'
            f"  <body>\n{links}\n  </body>\n</html>\n",
            encoding="utf-8",
        )

    links = "\n".join(f'    <a href="{n}/">{n}</a><br/>' for n in sorted(projects))
    (simple / "index.html").write_text(
        '<!DOCTYPE html>\n<html>\n  <head><meta charset="utf-8"/><title>Simple index</title></head>\n'
        f"  <body>\n{links}\n  </body>\n</html>\n",
        encoding="utf-8",
    )

    print(f"索引: {simple}（{len(projects)} 个项目 / {len(wheels)} 个 wheel）")
    for name, files in sorted(projects.items()):
        print(f"  {name}: {len(files)}")
    verify_index(root)
    return 0


def verify_index(root: Path) -> None:
    """回读 ``simple/``，按 PEP 503 的语义（相对链接 + ``#sha256=``）逐条验证。

    这里是唯一能证明「索引与 wheel 的相对位置、哈希都对」的地方：链接写错一两级
    目录、wheel 重新打包后没重建索引，都会在下游 ``--extra-index-url`` 时报
    "no matching distribution"，而不是在构建期。
    """
    simple = root / "simple"
    pages = sorted(simple.glob("*/index.html"))
    assert pages, f"{simple} 下没有任何项目页"
    for page in pages:
        html = page.read_text(encoding="utf-8")
        links = re.findall(r'<a href="([^"#]+)#sha256=([0-9a-f]{64})"', html)
        assert links, f"{page} 里没有带 sha256 的链接"
        for href, digest in links:
            target = (page.parent / href).resolve()
            assert target.is_file(), f"{page} 的链接指向不存在的文件: {href} -> {target}"
            assert hashlib.sha256(target.read_bytes()).hexdigest() == digest, (
                f"{page} 里 {target.name} 的 sha256 与实际文件不符（索引过期？）"
            )
    print(f"索引校验通过: {len(pages)} 个项目页，链接与 sha256 全部对得上")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--opencv", metavar="PREFIX", help="cmake 的安装前缀，产出 opencv wheel")
    ap.add_argument("--repair", metavar="WHEEL", help="pip 打出来的 wheel，auditwheel 修复后落盘")
    ap.add_argument("--ddddocr", metavar="SRC", help="ddddocr 源码目录，产出纯 python wheel")
    ap.add_argument("--emit-index", action="store_true", help="为 --out-dir 里已有的 wheel 生成 simple/")
    ap.add_argument("--out-dir", required=True, help="wheel 输出目录（--emit-index 时为索引所在目录）")
    ap.add_argument("--version", default="", help="--opencv 的版本号（写进 wheel 元数据）")
    ap.add_argument(
        "--expect-version",
        default="",
        help="断言产出的 ddddocr 版本，防止上游改版本号后与镜像 tag 不一致",
    )
    args = ap.parse_args()

    modes = [bool(args.opencv), bool(args.repair), bool(args.ddddocr), args.emit_index]
    if sum(modes) != 1:
        return die("--opencv / --repair / --ddddocr / --emit-index 必须且只能给一个")

    out_dir = Path(args.out_dir).resolve()
    if args.emit_index:
        return emit_index(out_dir)
    if args.opencv:
        if not args.version:
            return die("--opencv 需要同时给 --version")
        return build_opencv(Path(args.opencv).resolve(), args.version, out_dir)
    if args.repair:
        return repair_wheel(Path(args.repair).resolve(), out_dir)
    return build_ddddocr(Path(args.ddddocr).resolve(), out_dir, args.expect_version)


if __name__ == "__main__":
    sys.exit(main())
