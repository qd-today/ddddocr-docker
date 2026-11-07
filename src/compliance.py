#!/usr/bin/env python3
"""wheelhouse 合规层：deny 断言 + NOTICE / SOURCE-OFFER + CycloneDX SBOM。

由三个仓库的 ``pack_wheel.py`` 在收尾（``--emit-index``）时调用，产物落在 wheelhouse
根目录，随 ``FROM scratch`` 的 wheelhouse 镜像一起分发：

    /wheels/NOTICE.md                  组件清单 + 许可证 + 版权声明
    /wheels/SOURCE-OFFER.md            对应源码的获取途径（LGPL/GPL 义务）
    /wheels/licenses/LGPL-3.0.txt      LGPLv3 是 GPLv3 的补充条款，两份都要给
    /wheels/licenses/GPL-3.0.txt
    /wheels/licenses/LGPL-2.1.txt
    /wheels/sbom/<wheel>.cdx.json      每个 wheel 一份 CycloneDX 1.5
    /wheels/sbom/wheelhouse.cdx.json   汇总
    /wheels/components.json            所有随包组件的机器可读记录（下列文书的公共来源）
    /wheels/component-versions         构建期由 Dockerfile 写入的自编库版本（输入，非产物）
    /wheels/fossa-deps.yml             FOSSA 自行解析的依赖声明（非 Enterprise 路径，见下）

为什么不是「往 wheel 里塞」而是「放 wheelhouse 根目录」：改 wheel 要重算 RECORD 并让
上游算好的 SHA256SUMS 失效；而 wheelhouse 镜像本身也是对外发布的产物，把文书放在这一层
既满足随附义务，又不破坏 PEP 427 的完整性约束。

版本号从构建镜像的 ``/lib/apk/db/installed`` 反查（auditwheel 会把依赖改名成
``libfoo-<hash>.so.N``，去掉 hash 后按 apk 的文件清单匹配）。这一点很关键：需要精确版本
的恰好都是 apk 提供的 copyleft 组件；自编的 curl / ngtcp2 / nghttp3 是宽松许可，版本精度
不影响义务履行。

``fossa-deps.yml`` 是给 FOSSA 的入口，不是给人看的清单：``fossa sbom analyze``（直传
CycloneDX）是 Enterprise 订阅独占，普通订阅只能靠 ``fossa analyze`` 读这份文件。所以 apk
提供的库写成 ``referenced-dependencies``——FOSSA 拿 ref 去自己的知识库查许可证和漏洞，
结论由它得出；没有 apk 出处的自编库才写成 ``custom-dependencies``（只给许可证，无漏洞数据）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

APK_DB = Path("/lib/apk/db/installed")
OS_RELEASE = Path("/etc/os-release")

# --------------------------------------------------------------------------- #
# 硬禁止清单：命中的库一律让构建失败
#
# 只按「库名」禁，绝不按许可证禁——libstdc++ / libgcc_s / libgfortran 都是
# GPL-3.0-or-later WITH GCC-exception-3.1，运行时例外允许无条件随二进制分发，
# 按许可证一刀切会把这几个每个 C++ wheel 都有的库误杀。
# --------------------------------------------------------------------------- #
DEFAULT_DENY = (
    # GPL-3.0-or-later，Pillow 的可选编码器；Alpine 的 py3-pillow 就链了它
    "libimagequant*",
    # FFmpeg：LGPL-2.1（部分构建 GPL），opencv videoio 的主要 copyleft 来源
    "libavcodec*", "libavformat*", "libavutil*", "libswscale*",
    "libswresample*", "libavfilter*", "libavdevice*",
    # Qt5/Qt6：LGPL-3.0，非 headless 的 opencv wheel 会带
    "libQt5*", "libQt6*",
    # GStreamer / GPL 编解码器
    "libgst*", "libx264*", "libx265*", "libfdk-aac*",
    # videoio / highgui 一旦编进来就会拖 FFmpeg 与 Qt，本仓库只用 core/imgproc/imgcodecs
    "libopencv_videoio*", "libopencv_highgui*",
    # Intel IPP/ICV：专有许可
    "libippicv*", "libippiw*", "libippvm*",
    # GTK / readline：LGPL-2.1 / GPL-3.0，纯属误链检测
    "libgtk-3*", "libgtk-4*", "libreadline*",
)

# --------------------------------------------------------------------------- #
# 组件识别表：(正则, 组件名, SPDX 或自定义许可名, 上游源码地址)
#
# 与 DEFAULT_DENY 互补：这里列的是「允许随包，但要出现在 NOTICE 里」的东西，
# 包括必须给源码途径的 copyleft 组件。
# --------------------------------------------------------------------------- #
KNOWN = (
    (r"^libcurl\b",        "curl",         "curl",                                  "https://curl.se/download/"),
    (r"^libssl\b|^libcrypto\b", "OpenSSL",  "Apache-2.0",                            "https://github.com/openssl/openssl"),
    (r"^libnghttp2\b",     "nghttp2",      "MIT",                                   "https://github.com/nghttp2/nghttp2"),
    (r"^libnghttp3\b",     "nghttp3",      "MIT",                                   "https://github.com/ngtcp2/nghttp3"),
    (r"^libngtcp2",        "ngtcp2",       "MIT",                                   "https://github.com/ngtcp2/ngtcp2"),
    (r"^libidn2\b",        "libidn2",      "LGPL-3.0-or-later",                     "https://gitlab.com/libidn/libidn2"),
    (r"^libunistring\b",   "libunistring", "LGPL-3.0-or-later",                     "https://git.savannah.gnu.org/git/libunistring.git"),
    (r"^libpsl\b",         "libpsl",       "MIT",                                   "https://github.com/rockdaboot/libpsl"),
    (r"^libbrotli",        "brotli",       "MIT",                                   "https://github.com/google/brotli"),
    (r"^libz\.",           "zlib",         "Zlib",                                  "https://zlib.net/"),
    (r"^libzstd\b",        "zstd",         "BSD-3-Clause",                          "https://github.com/facebook/zstd"),
    (r"^libssh2\b",        "libssh2",      "BSD-3-Clause",                          "https://github.com/libssh2/libssh2"),
    (r"^libsfparse\b",     "sfparse",      "MIT",                                   "https://github.com/ngtcp2/sfparse"),
    (r"^libcares|^libc-ares", "c-ares",    "MIT",                                   "https://github.com/c-ares/c-ares"),
    (r"^libgsasl\b",       "gsasl",        "LGPL-2.1-or-later",                      "https://gitlab.com/gsasl/gsasl"),
    (r"^libsasl2\b",       "cyrus-sasl",   "BSD-3-Clause",                          "https://github.com/cyrusimap/cyrus-sasl"),
    (r"^libkrb5|^libgssapi|^libk5crypto|^libkdb5",
                           "krb5",         "MIT",                                   "https://github.com/krb5/krb5"),
    # libcom_err 来自 e2fsprogs 的 lib/et，不是 krb5 的一部分。上游 NOTICE 明确
    # "lib/et and lib/ss libraries ... under an MIT-style license"，com_err.c 头部是
    # MIT-SIPB 声明（保留 MIT 名称不得用于背书）。不能并进 krb5 条目。
    (r"^libcom_err",       "libcom_err",   "MIT",                                   "https://git.kernel.org/pub/scm/fs/ext2/e2fsprogs.git"),
    (r"^libss\b",          "libss",        "MIT",                                   "https://git.kernel.org/pub/scm/fs/ext2/e2fsprogs.git"),
    (r"^libext2fs|^libe2p\b", "e2fsprogs", "LGPL-2.0-or-later",                     "https://git.kernel.org/pub/scm/fs/ext2/e2fsprogs.git"),
    (r"^libuuid\b",        "libuuid",      "BSD-3-Clause",                          "https://git.kernel.org/pub/scm/fs/ext2/e2fsprogs.git"),
    (r"^libgfortran\b",    "libgfortran",  "GPL-3.0-or-later WITH GCC-exception-3.1", "https://gcc.gnu.org/git/gcc.git"),
    (r"^libgomp\b",        "libgomp",      "GPL-3.0-or-later WITH GCC-exception-3.1", "https://gcc.gnu.org/git/gcc.git"),
    (r"^libstdc\+\+",      "libstdc++",    "GPL-3.0-or-later WITH GCC-exception-3.1", "https://gcc.gnu.org/git/gcc.git"),
    (r"^libgcc_s\b",       "libgcc",       "GPL-3.0-or-later WITH GCC-exception-3.1", "https://gcc.gnu.org/git/gcc.git"),
    (r"^libopenblas",      "OpenBLAS",     "BSD-3-Clause",                          "https://github.com/OpenMathLib/OpenBLAS"),
    (r"^libkeyutils",      "keyutils",     "LGPL-2.1-or-later",                     "https://git.kernel.org/pub/scm/linux/kernel/git/dhowells/keyutils.git"),
    (r"^libutf8_validity|^libutf8_range", "utf8_range", "Apache-2.0",                 "https://github.com/protocolbuffers/utf8_range"),
    (r"^libsharpyuv",      "libwebp",      "BSD-3-Clause",                          "https://chromium.googlesource.com/webm/libwebp"),
    (r"^libquadmath",      "libquadmath",  "GPL-3.0-or-later WITH GCC-exception-3.1", "https://gcc.gnu.org/git/gcc.git"),
    (r"^libprotobuf",      "protobuf",     "BSD-3-Clause",                          "https://github.com/protocolbuffers/protobuf"),
    (r"^libabsl_",         "abseil-cpp",   "Apache-2.0",                            "https://github.com/abseil/abseil-cpp"),
    (r"^libre2\b",         "RE2",          "BSD-3-Clause",                          "https://github.com/google/re2"),
    (r"^libicu",           "ICU",          "ICU",                                   "https://github.com/unicode-org/icu"),
    (r"^libjpeg",          "libjpeg-turbo", "IJG AND BSD-3-Clause",                 "https://github.com/libjpeg-turbo/libjpeg-turbo"),
    (r"^libpng",           "libpng",       "libpng-2.0",                            "https://github.com/pnggroup/libpng"),
    (r"^libwebp",          "libwebp",      "BSD-3-Clause",                          "https://chromium.googlesource.com/webm/libwebp"),
    (r"^libtiff",          "libtiff",      "libtiff",                               "https://gitlab.com/libtiff/libtiff"),
    (r"^libavif",          "libavif",      "BSD-2-Clause",                          "https://github.com/AOMediaCodec/libavif"),
    (r"^libopencv_",       "OpenCV",       "Apache-2.0",                            "https://github.com/opencv/opencv"),
    (r"^libxcb\b",         "libxcb",       "X11",                                   "https://gitlab.freedesktop.org/xorg/lib/libxcb"),
    (r"^libXau\b|^libXdmcp\b", "libXau",    "MIT",                                   "https://gitlab.freedesktop.org/xorg/lib/libxau"),
    (r"^liblcms2\b",       "Little CMS",   "MIT",                                   "https://github.com/mm2/Little-CMS"),
    (r"^liblzma\b",        "xz-utils",     "0BSD",                                  "https://github.com/tukaani-project/xz"),
    (r"^libfreetype\b",    "FreeType",     "FTL",                                   "https://gitlab.freedesktop.org/freetype/freetype"),
    (r"^libharfbuzz\b",    "HarfBuzz",     "MIT",                                   "https://github.com/harfbuzz/harfbuzz"),
)

# 双许可时优先选宽松分支：FreeType 是 FTL OR GPL-2.0-or-later，选 FTL 就没有 GPL 义务；
# xz 是 0BSD AND LGPL-2.1-or-later（库本体 0BSD）。不选分支会让 NOTICE 里凭空多出义务。
PERMISSIVE = (
    "0BSD", "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "FTL", "Zlib",
    "ISC", "Unlicense", "IJG", "libpng-2.0", "ICU", "X11", "curl", "NCSA",
    "BSL-1.0", "JSON", "cc-pd", "public-domain",
)


def elect_permissive(lic: str) -> str:
    """``"FTL OR GPL-2.0-or-later"`` -> ``"FTL"``；无法判断时原样返回。"""
    parts = [p.strip() for p in re.split(r"\s+OR\s+", lic) if p.strip()]
    if len(parts) < 2:
        return lic
    for part in parts:
        if part in PERMISSIVE:
            return part
    return lic


FAMILY = re.compile(r"\b(A?GPL|LGPL)\b")


def _terms(expr: str) -> set[str]:
    return {t.strip("() ") for t in re.split(r"\s+(?:OR|AND|WITH)\s+", expr) if t.strip("() ")}


def pick_license(apk_lic: str, curated: str) -> tuple[str, str]:
    """在「apk 的 L: 字段」和「KNOWN 表里人工核过的库级许可证」之间取值。

    Alpine 的 ``L:`` 描述的是**整个源码包**，包含没有随 wheel 分发的命令行工具和守护
    进程，因此经常给出过宽的结论。两个实例：

    * ``libidn2``：apk 写 ``GPL-2.0-or-later OR LGPL-3.0-or-later``，我们只分发库，
      合法地选 LGPL-3.0-or-later。
    * ``keyutils``：apk 写 ``GPL-2.0-or-later AND LGPL-2.0-or-later``（GPL 管 keyctl
      等工具，LGPL 管 libkeyutils）。直接照抄会让 NOTICE 凭空多出一条 GPL 源码义务，
      而 ``keyutils-libs`` 子包里只有 ``usr/lib``，上游 ``keyutils.c`` 头部写的是
      "GNU Lesser General Public License ... version 2 ... or any later version"，
      随包附的 ``LICENCE.LGPL`` 是 2.1 文本，取 LGPL-2.1-or-later 稳妥。

    判定规则：curated 与 apk 表达式落在同一 copyleft 家族时以 curated 为准（库级精修），
    否则照常从 apk 表达式里挑宽松分支。返回值第二项是留痕说明，写进 NOTICE 供审计。
    """
    if not apk_lic or apk_lic == "unknown":
        return curated, ""
    if curated == apk_lic:
        return curated, ""       # apk 与人工核对结论一致，无需留痕
    if "GCC-exception" in curated:
        # GCC 运行时库的授权写在各库源码头部（GPL-3.0-or-later WITH GCC-exception-3.1），
        # apk 里记的是整个 gcc 包的表达式（GPL-2 AND LGPL-2.1），与这几个库无关。
        return curated, f"apk: {apk_lic}（GCC 运行时库例外条款，不采信 apk 元数据）"
    if curated and curated in _terms(apk_lic):
        # 一个 .so 只可能落在一种许可下，而 apk 的 AND 是源码包里所有文件许可的并集
        # （例如 e2fsprogs 的 libcom_err 是 MIT，其余工具是 GPL-2）。同名分支可以取，
        # 但要在留痕里写明这是「多许可源码包里的本库分支」而不是整体结论。
        why = "源码包为多许可 AND，本库本体采用该分支" if re.search(r"\sAND\s", apk_lic) else "取同名分支"
        return curated, f"apk: {apk_lic}（{why}）"
    if FAMILY.search(curated) and FAMILY.search(apk_lic):
        families = {m.group(0).upper() for m in FAMILY.finditer(apk_lic)}
        if FAMILY.search(curated).group(0).upper() in families:
            return curated, f"apk: {apk_lic}（仅分发库本体，取库级许可）"
    elected = elect_permissive(apk_lic)
    note = f"apk: {apk_lic}" if elected != apk_lic else ""
    return elected, note

COPYLEFT = re.compile(r"\b(?:A?GPL|LGPL|MPL|EPL|CPOL)", re.IGNORECASE)
HASH_SUFFIX = re.compile(r"-[0-9a-f]{8}(?=\.so)")
SO_VERSION = re.compile(r"(\.so(\.[0-9]+)+)$")


@dataclass
class Component:
    lib: str
    name: str
    version: str
    license: str
    url: str
    origin: str          # apk 包名，或 "self-built"
    files: list[str] = field(default_factory=list)
    note: str = ""       # 许可证判定留痕（apk 声明的原始表达式）
    arch: str = ""       # apk 的 A: 字段，写 fossa-deps.yml 的 apk 引用时要用

    @property
    def is_copyleft(self) -> bool:
        return bool(COPYLEFT.search(self.license))


# --------------------------------------------------------------------------- #
# apk 数据库
# --------------------------------------------------------------------------- #
def load_apk_index() -> dict[str, tuple[str, str, str, str]]:
    """返回 basename -> (包名, 版本, 许可证, 架构)。没有 apk db（非 Alpine 构建机）时返回空表。"""
    index: dict[str, tuple[str, str, str, str]] = {}
    if not APK_DB.is_file():
        return index
    for block in APK_DB.read_text(encoding="utf-8", errors="ignore").split("\n\n"):
        pkg = version = lic = arch = None
        entries: list[str] = []
        directory = ""
        for line in block.splitlines():
            if line.startswith("P:"):
                pkg = line[2:]
            elif line.startswith("V:"):
                version = line[2:]
            elif line.startswith("L:"):
                lic = line[2:]
            elif line.startswith("A:"):
                arch = line[2:]
            elif line.startswith("F:"):
                directory = line[2:]
            elif line.startswith("R:"):
                entries.append(f"{directory}/{line[2:]}".lstrip("/"))
        if not pkg or not version:
            continue
        for path in entries:
            key = path.rsplit("/", 1)[-1]
            index.setdefault(key, (pkg, version, lic or "unknown", arch or ""))
            flat = SO_VERSION.sub(".so", key)
            if flat != key:
                index.setdefault(flat, (pkg, version, lic or "unknown", arch or ""))
    return index


def clean_lib(basename: str) -> str:
    """去掉 auditwheel 加在 .so 前面的 8 位 hash。"""
    return HASH_SUFFIX.sub("", basename)


def classify(lib: str, apk: dict[str, tuple[str, str, str, str]]) -> Component:
    cleaned = clean_lib(lib)
    origin, version, apk_lic, arch = "self-built", "", "", ""
    hit = apk.get(cleaned) or apk.get(SO_VERSION.sub(".so", cleaned))
    if hit:
        origin, version, apk_lic, arch = hit

    for pattern, name, lic, url in KNOWN:
        if re.search(pattern, cleaned):
            resolved, note = pick_license(apk_lic, lic)
            return Component(
                lib=lib, name=name, version=version,
                license=resolved, url=url, origin=origin, files=[lib], note=note,
                arch=arch,
            )
    resolved, note = pick_license(apk_lic, "unknown")
    return Component(
        lib=lib, name=cleaned, version=version,
        license=resolved, url="", origin=origin, files=[lib], note=note, arch=arch,
    )


# --------------------------------------------------------------------------- #
# wheel 扫描
# --------------------------------------------------------------------------- #
def scan_wheel(wheel: Path, apk: dict[str, tuple[str, str, str]]) -> list[Component]:
    merged: dict[str, Component] = {}
    with zipfile.ZipFile(wheel) as zf:
        for info in zf.infolist():
            # auditwheel 把依赖收在 <dist>.libs/ 下，注意没有前导斜杠
            if info.is_dir() or ".libs/" not in info.filename:
                continue
            name = Path(info.filename).name
            if ".so" not in name:
                continue
            comp = classify(name, apk)
            key = f"{comp.name}@{comp.version}"
            if key in merged:
                merged[key].files.append(name)
            else:
                merged[key] = comp
    return sorted(merged.values(), key=lambda c: c.name.lower())


def wheel_meta(wheel: Path) -> tuple[str, str]:
    """从 wheel 文件名取 (distribution, version)。"""
    parts = wheel.name.split("-")
    return parts[0], parts[1] if len(parts) > 1 else ""


# --------------------------------------------------------------------------- #
# deny 断言
# --------------------------------------------------------------------------- #
def deny_check(wheel: Path, comps: list[Component], patterns: list[str]) -> None:
    import fnmatch

    hits: list[str] = []
    for comp in comps:
        for f in comp.files:
            for pat in patterns:
                if fnmatch.fnmatch(clean_lib(f), pat) or fnmatch.fnmatch(f, pat):
                    hits.append(f"{wheel.name}: {f}（匹配 {pat}）")
    if hits:
        raise SystemExit(
            "错误: 分发包里出现禁止的库——这些许可证不允许随本 wheel 分发：\n  "
            + "\n  ".join(sorted(set(hits)))
            + "\n如果要放行，先把组件加进 compliance.py 的 KNOWN 表并在 NOTICE 里声明义务。"
        )


# --------------------------------------------------------------------------- #
# 产物
# --------------------------------------------------------------------------- #
def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_notice(root: Path, per_wheel: dict[str, list[Component]],
                 hints: dict[str, str] | None = None) -> None:
    lines = [
        "# NOTICE",
        "",
        "本目录（wheelhouse）随附的 wheel 内含下列第三方组件。此文件由 `pack_wheel.py`",
        "在构建时从 wheel 的 `.libs/` 实测生成，不是手工维护的清单。",
        "",
        f"生成时间：{utc_now()}",
        "",
    ]
    for wheel_name, comps in sorted(per_wheel.items()):
        dist, ver = wheel_meta(Path(wheel_name))
        lines += [f"## {wheel_name}", ""]
        if not comps:
            lines += ["（无随包的原生依赖）", ""]
            continue
        lines += ["| 组件 | 版本 | 许可证 |", "| --- | --- | --- |"]
        for c in comps:
            lines.append(f"| {c.name} | {c.version or '见上游'} | {c.license} |")
        lines.append("")

    gcc_rle = re.compile(r"GCC-exception", re.IGNORECASE)
    copyleft = sorted(
        {(c.name, c.version, c.license) for cs in per_wheel.values() for c in cs
         if c.is_copyleft and not gcc_rle.search(c.license)}
    )
    gcc_libs = sorted(
        {c.name for cs in per_wheel.values() for c in cs if gcc_rle.search(c.license)}
    )
    if copyleft:
        lines += [
            "## 需要履行义务的组件",
            "",
            "下列组件采用 copyleft 许可，随二进制分发时的义务见 `SOURCE-OFFER.md`，",
            "许可证全文见 `licenses/`。",
            "",
            "| 组件 | 版本 | 许可证 |",
            "| --- | --- | --- |",
        ]
        for name, ver, lic in copyleft:
            lines.append(f"| {name} | {ver or '见上游'} | {lic} |")
        lines.append("")
    if gcc_libs:
        lines += [
            "## GCC 运行时库（不产生源码义务）",
            "",
            "下列组件采用 GPL-3.0-or-later WITH GCC-exception-3.1。该例外条款明确允许",
            "与任意许可的代码链接并分发，因此不要求提供本项目源码，无需列入 SOURCE-OFFER：",
            "",
            "　" + "、".join(gcc_libs),
            "",
        ]
    built = sorted(
        {(c.name, c.version or (hints or {}).get(c.name.lower(), ""), c.origin)
         for cs in per_wheel.values() for c in cs
         if hints and c.name.lower() in hints}
    )
    if built:
        lines += [
            "## 本项目自编的组件",
            "",
            "下列二进制由本项目在构建时自行编译，不是从 apk 安装的。它们的许可证结论按",
            "源码本体判定，在 FOSSA 上的声明方式取决于能否借用 apk 出处：",
            "",
            "| 组件 | 版本 | FOSSA 上的声明方式 |",
            "| --- | --- | --- |",
        ]
        for name, ver, origin in built:
            if origin and origin != "self-built":
                how = (f"referenced——借用 apk 包 `{origin}` 的同名文件出处，"
                       "版本与 apk 包同线，因此带漏洞数据")
            else:
                how = "custom——apk 里没有对应包，许可证由本项目担保（无漏洞数据）"
            lines.append(f"| {name} | {ver or '未标注'} | {how} |")
        lines.append("")
    notes = sorted(
        {(c.name, c.version, c.license, c.note) for cs in per_wheel.values() for c in cs if c.note}
    )
    if notes:
        lines += [
            "## 许可证判定留痕",
            "",
            "Alpine 的 apk 元数据描述的是整个源码包（含未随本 wheel 分发的工具与守护进程），",
            "结论比库本体更宽。下表中「apk 声明」是原始记录，「采用」是按库本体收敛后的结论：",
            "",
            "| 组件 | 版本 | 采用 | apk 声明与判定说明 |",
            "| --- | --- | --- | --- |",
        ]
        for name, ver, lic, note in notes:
            lines.append(f"| {name} | {ver or '见上游'} | {lic} | {note} |")
        lines.append("")
    (root / "NOTICE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_source_offer(root: Path, per_wheel: dict[str, list[Component]]) -> None:
    # GCC 运行时库带例外条款，不产生源码义务，单独说明而不是混进义务表
    gcc_rle = re.compile(r"GCC-exception", re.IGNORECASE)
    copyleft = sorted(
        {(c.name, c.version, c.license, c.url, c.origin)
         for cs in per_wheel.values() for c in cs
         if c.is_copyleft and not gcc_rle.search(c.license)}
    )
    lines = [
        "# SOURCE OFFER / 源码获取途径",
        "",
        "本 wheelhouse 的二进制分发包内含下列 copyleft 组件。按各自许可证的要求，",
        "这里给出**对应源码**的获取途径。",
        "",
        "获取方式统一为下列两种，任选其一：",
        "",
        "1. 从构建所用的 Alpine 版本按包名取源码包：",
        "   `https://gitlab.alpinelinux.org/alpine/aports/-/tree/<alpine-version>/main/<package>`",
        "2. 直接取上游仓库的对应 tag（见下表 URL）。",
        "",
        "如上述途径均不可达，可在本仓库提 issue 索取，我们提供与所分发二进制完全对应的源码。",
        "",
        "> LGPLv3 与 LGPLv2.1 的要求是「允许用户用修改后的库重新链接」。本 wheelhouse 里的",
        "> 依赖全部是独立的 `.so` 文件（auditwheel 收在 `<dist>.libs/` 下，按 SONAME 动态",
        "> 加载），用户可以用自行编译的同名 `.so` 直接替换，无需重新链接本包，因此动态链接",
        "> 方式已满足可替换性要求。",
        "",
        "| 组件 | 版本 | 许可证 | Alpine 包 | 上游源码 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, ver, lic, url, origin in copyleft:
        pkg = origin if origin != "self-built" else "—（自编）"
        lines.append(f"| {name} | {ver or '见上游'} | {lic} | {pkg} | {url or '见上游仓库'} |")
    if not copyleft:
        lines.append("| （无） | — | — | — | — |")

    lines += [
        "",
        "## 关于 GCC 运行时库",
        "",
        "`libstdc++` / `libgcc_s` / `libgfortran` / `libgomp` 采用 GPL-3.0-or-later",
        "WITH GCC-exception-3.1。该例外条款明确允许把它们与任意许可的代码链接并分发，",
        "不产生对本项目源码的要求，因此它们列在 NOTICE 里但不在本文的源码义务范围内。",
        "",
    ]
    (root / "SOURCE-OFFER.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


SPDX_LICENSES = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Zlib", "MPL-2.0",
    "LGPL-2.1-only", "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later",
    "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only", "GPL-3.0-or-later",
    "BSL-1.0", "Unlicense", "CC0-1.0", "0BSD", "X11", "IJG", "libpng-2.0", "ICU",
}


def license_entry(lic: str) -> dict:
    first = lic.split(" AND ")[0].split(" OR ")[0].strip()
    if first in SPDX_LICENSES:
        return {"license": {"id": first}}
    return {"license": {"name": lic}}


def build_sbom(wheel_name: str, comps: list[Component]) -> dict:
    dist, ver = wheel_meta(Path(wheel_name))
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": utc_now(),
            "tools": [{"vendor": "qd-today", "name": "pack_wheel.py compliance", "version": "1"}],
            "component": {
                "type": "library",
                "name": dist,
                "version": ver,
                "purl": f"pkg:pypi/{dist}@{ver}",
            },
            "properties": [
                {"name": "qd:wheel", "value": wheel_name},
            ],
        },
        "components": [
            {
                "type": "library",
                "name": c.name,
                "version": c.version or "unknown",
                "bom-ref": f"{c.name}@{c.version or 'unknown'}",
                **({"purl": f"pkg:apk/alpine/{c.origin}@{c.version}"} if c.origin != "self-built" and c.version else {}),
                "licenses": [license_entry(c.license)],
                "properties": [
                    {"name": "qd:bundled-files", "value": ", ".join(sorted(c.files))},
                    {"name": "qd:origin", "value": c.origin},
                ],
            }
            for c in comps
        ],
    }


def write_sbom(root: Path, per_wheel: dict[str, list[Component]]) -> None:
    sbom_dir = root / "sbom"
    if not sbom_dir.is_dir():
        sbom_dir.mkdir(parents=True, exist_ok=True)
    all_comps: dict[str, Component] = {}
    for wheel_name, comps in per_wheel.items():
        (sbom_dir / f"{Path(wheel_name).stem}.cdx.json").write_text(
            json.dumps(build_sbom(wheel_name, comps), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        for c in comps:
            all_comps.setdefault(f"{c.name}@{c.version}", c)
    merged = build_sbom("wheelhouse", sorted(all_comps.values(), key=lambda c: c.name.lower()))
    merged["metadata"]["component"] = {"type": "application", "name": "wheelhouse", "version": "aggregate"}
    (sbom_dir / "wheelhouse.cdx.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


FOSSA_DEPS = "fossa-deps.yml"
# 构建期由 Dockerfile 从 ARG 写入的自编库版本，一行一个：``curl=8.23.0``。
# 版本在构建时就知道，不该靠人往 CI 里塞环境变量（QD_LIB_VERSIONS 只留作临时覆盖）。
COMPONENT_VERSIONS = "component-versions"
# 所有随包组件的机器可读记录：NOTICE / SBOM / fossa-deps 三者的公共来源。
COMPONENTS_JSON = "components.json"


def load_os_release() -> tuple[str, str]:
    """返回 (ID, VERSION_ID)，例如 ("alpine", "3.24.3")。"""
    if not OS_RELEASE.is_file():
        return "", ""
    values: dict[str, str] = {}
    for line in OS_RELEASE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values.get("ID", ""), values.get("VERSION_ID", "")


def load_version_hints(root: Path | None = None,
                       env: dict[str, str] | None = None) -> dict[str, str]:
    """自编库的版本，两个入口，环境变量优先。

    1. ``<wheelhouse>/component-versions``（主路径）：构建期由 Dockerfile 从 ARG 写入，
       一行一个 ``curl=8.23.0``，``#`` 起注释。键名必须用 **KNOWN 表里的组件名**
       （如 ``OpenBLAS``、``curl``），不是 Dockerfile 的 ARG 名，也不是 wheel 名。
    2. ``QD_LIB_VERSIONS="curl=8.23.0,OpenBLAS=0.3.30"``：临时覆盖。

    自编的库在 apk 数据库里查不到版本，只能由构建方告知。查不到又没填就写 "unknown"，
    不影响许可证结论，只影响 FOSSA 页面上的版本显示。

    这个名字集合还有第二个用途：出现在这里的组件就是「我们自己编的」。
    借用了 apk 出处的自编库（如 curl 覆写 apk libcurl）靠这一条才能和「apk 原装库」区分开。
    """
    hints: dict[str, str] = {}

    def _feed(raw: str) -> None:
        for item in raw.replace(";", ",").split(","):
            name, sep, version = item.partition("=")
            if sep and name.strip() and version.strip():
                hints[name.strip().lower()] = version.strip()

    if root is not None:
        f = Path(root) / COMPONENT_VERSIONS
        if f.is_file():
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                _feed(line.split("#", 1)[0])
    _feed((env or os.environ).get("QD_LIB_VERSIONS", ""))
    return hints


def apk_refs_of(comp: Component, apk: dict[str, tuple[str, str, str, str]]) -> list[tuple[str, str, str]]:
    """返回这个组件里各库文件所属的 apk 包 [(包名, 版本, 架构), ...]。

    为什么要按文件拆而不是直接用 ``Component.origin``：一个 Component 是「同一 upstream
    多个库」合并出来的（libwebp / libwebpdemux / libwebpmux / libsharpyuv 在 NOTICE 里
    只占 libwebp 一行），origin 只剩第一个命中的包。而 FOSSA 的 apk 引用必须精确到包，
    所以按合并前记录的每个文件名逐个反查。
    """
    found: set[tuple[str, str, str]] = set()
    for f in comp.files or [comp.lib]:
        cleaned = clean_lib(f)
        hit = apk.get(cleaned) or apk.get(SO_VERSION.sub(".so", cleaned))
        if hit:
            found.add((hit[0], hit[1], hit[3]))
    return sorted(found)


def write_components_manifest(root: Path, per_wheel: dict[str, list[Component]],
                              hints: dict[str, str]) -> None:
    """生成 ``components.json``：每条随包组件的机器可读记录。

    为什么单独出一份：NOTICE 给人看、SBOM 给工具吃、fossa-deps 给 FOSSA 读，
    三者字段口径不同，容易各写各的、互相漂移。这份 json 是它们的公共来源，
    审计时也只需要核对这一处。

    ``selfBuilt`` 的判据是「名字出现在 component-versions 里」——apk 原装库的版本来自
    apk 数据库，不会出现在那份文件里，所以这个标志能准确区分「我们编的」和「apk 装的」。
    """
    os_id, os_version = load_os_release()
    wheels: dict[str, list[str]] = {}
    merged: dict[str, dict] = {}
    for wheel_name, comps in sorted(per_wheel.items()):
        wheels[wheel_name] = [c.name for c in comps]
        for c in comps:
            key = c.name.lower()
            entry = merged.get(key)
            if entry is None:
                entry = merged[key] = {
                    "name": c.name,
                    "version": c.version or hints.get(key, ""),
                    "license": c.license,
                    "selfBuilt": key in hints,
                    "apkPackage": None if c.origin == "self-built" else c.origin,
                    "url": c.url,
                    "files": [],
                    "wheels": [],
                }
            for f in c.files or [c.lib]:
                if f not in entry["files"]:
                    entry["files"].append(f)
            if wheel_name not in entry["wheels"]:
                entry["wheels"].append(wheel_name)

    doc = {
        "generatedAt": utc_now(),
        "os": {"id": os_id, "version": os_version},
        "wheels": wheels,
        "components": [merged[k] for k in sorted(merged)],
    }
    (root / COMPONENTS_JSON).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_fossa_deps(root: Path, per_wheel: dict[str, list[Component]]) -> tuple[int, int]:
    """生成 ``fossa-deps.yml``，让 ``fossa analyze`` 在非 Enterprise 订阅下也能识别这些库。

    两条路径分工：

    * 有 apk 出处的库 -> ``referenced-dependencies``（``type: apk``）。FOSSA 后端拿这个
      ref 去**它自己的知识库**查许可证**和漏洞**——referenced 是唯一支持漏洞的类型，
      也就是说「这是什么许可证」这个结论由 FOSSA 自己得出，不是我们喂给它的。
    * 自编的库（curl / ngtcp2 / nghttp3 / OpenBLAS 这类没有 apk 包的）->
      ``custom-dependencies``，license 必填，用 KNOWN 表里核过的值。

    ``fossa sbom analyze`` 是 Enterprise 独占，非企业版只能靠 ``fossa analyze`` 读
    fossa-deps 文件。该文件要求至少有一条有效依赖，全空时不生成（免得 FOSSA 报错）。

    返回 (apk 引用数, 自编依赖数)。
    """
    os_id, os_version = load_os_release()
    can_ref = bool(os_id and os_version)
    hints = load_version_hints(root)
    apk = load_apk_index() if can_ref else {}

    refs: set[tuple[str, str, str]] = set()
    customs: dict[tuple[str, str], Component] = {}
    for comps in per_wheel.values():
        for c in comps:
            hits = apk_refs_of(c, apk) if apk else []
            if hits:
                refs.update(hits)
            else:
                customs.setdefault((c.name, c.version or hints.get(c.name.lower(), "unknown")), c)

    if not refs and not customs:
        return 0, 0

    lines = [
        "# 由 pack_wheel.py --compliance 从 wheel 的 .libs/ 实测生成，不要手改。",
        "#",
        "# 用途: 非 Enterprise 订阅下，`fossa analyze` 只能读这份文件才能看到随包的原生库：",
        "#   referenced-dependencies (type: apk) —— FOSSA 自己去查 Alpine 包的许可证与漏洞",
        "#   custom-dependencies —— 自编库，没有 apk 出处，许可证据 compliance.py 的 KNOWN 表",
        f"# 基础镜像: {os_id or '未知'} {os_version or ''}".rstrip(),
        "# apk 归属按 /lib/apk/db/installed 的文件清单判定；同路径被我们自己的构建覆盖时"
        "（如 curl）仍记在该 apk 包名下。",
    ]
    if not can_ref:
        lines.append("# 未读到 /etc/os-release，全部按自编库处理（apk 引用必须有 os 与 osVersion）")
    unknown_versions = sorted({n for (n, v) in customs if v == "unknown"})
    if unknown_versions:
        lines.append("# 版本未知（自编库，apk 库里没有）: " + "、".join(unknown_versions))
        lines.append('# 补版本: 设 QD_LIB_VERSIONS="名字=版本,名字=版本" 后重新生成')
    lines.append("")
    if refs:
        lines.append("referenced-dependencies:")
        for pkg, version, arch in sorted(refs):
            lines += [
                f'  - name: "{pkg}"',
                f'    version: "{version}"',
                '    type: "apk"',
                f'    arch: "{arch}"',
                f'    os: "{os_id}"',
                f'    osVersion: "{os_version}"',
            ]
    if customs:
        lines.append("custom-dependencies:")
        for (name, version), c in sorted(customs.items()):
            lines += [
                f'  - name: "{name}"',
                f'    version: "{version}"',
                f'    license: "{c.license}"',
            ]
            if c.url:
                lines += ["    metadata:", f'      homepage: "{c.url}"']
    (root / FOSSA_DEPS).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(refs), len(customs)


def needed_texts(per_wheel: dict[str, list[Component]]) -> list[str]:
    """按实际出现的 copyleft 决定要随附哪些许可证全文。

    只带用得上的，避免 wheelhouse 里出现一个跟义务无关的 licenses/ 目录：
    LGPLv3 第 3 条要求同时给出 GPLv3 与 LGPLv3 两份；LGPLv2.1 自带一份即可。
    GCC 运行时库的 GPL 义务被 GCC-exception-3.1 豁免，不触发 GPL 全文。
    """
    lics = {c.license for cs in per_wheel.values() for c in cs}
    need: list[str] = []
    if any("LGPL-3.0" in l for l in lics):
        need += ["LGPL-3.0.txt", "GPL-3.0.txt"]
    if any("LGPL-2.1" in l for l in lics):
        need.append("LGPL-2.1.txt")
    return need


def copy_licenses(root: Path, source: Path, names: list[str]) -> list[str]:
    if not names:
        return []
    target = root / "licenses"
    if not target.is_dir():
        target.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in names:
        src = source / name
        if src.is_file():
            shutil.copyfile(src, target / name)
            copied.append(name)
    return copied


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def license_dir_default() -> Path:
    """许可证全文所在目录：优先环境变量，其次与脚本同级，最后是镜像内的固定路径。"""
    import os

    env = os.environ.get("QDPACK_LICENSES")
    if env:
        return Path(env)
    for candidate in (
        Path(__file__).resolve().parent / "licenses",
        Path("/usr/local/share/qdpack/licenses"),
    ):
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent / "licenses"


def unknown_check(per_wheel: dict[str, list[Component]], allowed: bool) -> None:
    """许可证未知的组件一律拦下。

    合规门禁里「不知道」和「不允许」等价：清单里出现 unknown 说明 KNOWN 表没覆盖到，
    此时放行等于把一个未评估的许可证直接发出去。补齐 KNOWN 表后这条自然通过。
    """
    if allowed:
        return
    unknown = sorted(
        {f"{c.name}（{next(iter(c.files))}）" for cs in per_wheel.values() for c in cs
         if c.license in ("unknown", "", None)}
    )
    if unknown:
        raise SystemExit(
            "错误: 下列随包库的许可证无法识别，禁止放行：\n  "
            + "\n  ".join(unknown)
            + "\n把它们补进 compliance.py 的 KNOWN 表；确认无风险时可用 --allow-unknown 跳过。"
        )


def run(root: Path, deny: list[str] | None = None, license_dir: Path | None = None,
        allow_unknown: bool = False) -> None:
    wheels = sorted(root.glob("*.whl"))
    if not wheels:
        raise SystemExit(f"错误: {root} 下没有 .whl，无法做合规检查")

    deny = list(deny) if deny else list(DEFAULT_DENY)
    apk = load_apk_index()
    if not apk:
        print("提示: 没找到 /lib/apk/db/installed，组件版本将标注「见上游」", file=sys.stderr)

    per_wheel: dict[str, list[Component]] = {}
    for wheel in wheels:
        comps = scan_wheel(wheel, apk)
        deny_check(wheel, comps, deny)
        per_wheel[wheel.name] = comps
        flagged = [c for c in comps if c.is_copyleft]
        print(f"  {wheel.name}: {len(comps)} 个随包组件，其中 copyleft {len(flagged)} 个")

    unknown_check(per_wheel, allow_unknown)

    hints = load_version_hints(root)
    write_notice(root, per_wheel, hints)
    write_source_offer(root, per_wheel)
    write_sbom(root, per_wheel)
    write_components_manifest(root, per_wheel, hints)
    n_ref, n_custom = write_fossa_deps(root, per_wheel)
    lic_dir = license_dir or license_dir_default()
    need = needed_texts(per_wheel)
    copied = copy_licenses(root, lic_dir, need)
    missing = [n for n in need if n not in copied]
    if missing:
        raise SystemExit(
            f"错误: {lic_dir} 里缺少 {', '.join(missing)}"
            "（随附许可证全文是义务的一部分，缺一份就等于没履行）"
        )

    parts = ["NOTICE.md", "SOURCE-OFFER.md", COMPONENTS_JSON]
    if copied:
        parts.append(f"licenses/{', '.join(copied)}")
    else:
        parts.append("licenses/（无 copyleft 组件，未随附全文）")
    parts.append("sbom/*.cdx.json")
    if n_ref or n_custom:
        parts.append(f"{FOSSA_DEPS}（apk 引用 {n_ref} / 自编 {n_custom}）")
    else:
        parts.append(f"{FOSSA_DEPS}（未生成，无可用条目）")
    print("合规产物: " + " / ".join(parts))
    print(f"deny 断言通过（{len(deny)} 条模式），无未识别许可证")
