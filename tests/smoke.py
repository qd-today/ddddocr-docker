#!/usr/bin/env python3
"""runtime 镜像冒烟测试。容器内经 stdin 执行，脚本不进镜像：

    docker run --rm -i --platform <platform> <image> python3 - <platform> <ddddocr 版本> < tests/smoke.py

    # 例如
    docker run --rm -i --platform linux/riscv64 <image> python3 - linux/riscv64 1.6.1 < tests/smoke.py

验的六件事，各自挡一类回归：

1. **没有 wheel 残留** —— wheelhouse 只在构建期 bind mount，`/wheels`、`/w` 出现在
   runtime 镜像里说明那两条 RUN 的挂载没被回收（体积白涨）；
2. **动态链接全部可解析** —— 对 cv2 / PIL 的 `.so` 跑 `ldd`，出现 `not found` 就说明
   auditwheel 没把依赖收进 `.libs/`、或 RPATH 改错了。这条比「能 import」更早失败：
   import 只用得到被 dlopen 的那部分符号；
3. **Pillow 自编译契约** —— 13.x + jpg/zlib/webp + 绝不链 libimagequant（GPL-3.0）；
4. **libprotobuf-lite 由 wheel 提供** —— 它必须来自 onnxruntime.libs/，系统里不该再
   有 apk 装的那一份（改成 wheelhouse 分发后 apk 那条已删）；
5. **产物架构** —— 编译产物是目标架构的机器码（QEMU 下构建时 cmake 的架构探测被
   uname 骗过是常见事故：能编译、能跑，产物却是宿主架构）；
6. **真实识别链路** —— 依赖 → 模型加载 → 图像编码 → ONNX 前向 → 解码输出。

不断言识别准确率：合成字体与真实验证码分布不同，准确率断言会 flaky；这里只验证链路
完整、输出结构合理。
"""

import glob
import importlib.metadata
import io
import os
import platform
import struct
import subprocess
import sys

# ELF e_machine 编码（/usr/include/elf.h）
ELF_MACHINE = {
    "linux/amd64": 62, "linux/arm64": 183, "linux/arm/v7": 40,
    "linux/ppc64le": 21, "linux/riscv64": 243, "linux/loong64": 258,
}


def elf_machine(path):
    """读 ELF 头的 e_machine。不依赖 readelf/file（镜像里没有这些工具）。"""
    with open(path, "rb") as handle:
        header = handle.read(20)
    assert header[:4] == b"\x7fELF", "%s 不是 ELF 文件" % path
    endian = "<" if header[5] == 1 else ">"   # EI_DATA: 1=小端 2=大端
    return struct.unpack(endian + "H", header[18:20])[0]


def check_arch(platform_name, patterns):
    """断言镜像里的原生产物确实是目标平台的机器码。"""
    expected = ELF_MACHINE.get(platform_name)
    if expected is None:
        print("跳过 ELF 架构校验（未知平台 %r）" % platform_name)
        return

    checked = 0
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            got = elf_machine(path)
            assert got == expected, (
                "%s 的 ELF machine=%d，期望 %d（%s）—— 构建时架构探测错了"
                % (path, got, expected, platform_name)
            )
            checked += 1
    assert checked, "没有找到可校验的原生产物（检查 glob 模式是否写错）"
    print("ELF 架构校验通过：%d 个产物 = %s（e_machine=%d）" % (checked, platform_name, expected))


def site_packages():
    import sysconfig

    return sysconfig.get_paths()["purelib"]


def check_no_wheel_leftovers():
    leftovers = [p for p in ("/wheels", "/w") if os.path.exists(p)]
    if leftovers:
        raise SystemExit("runtime 镜像里残留 wheel 目录: %s" % ", ".join(leftovers))
    print("未发现 /wheels 或 /w（wheelhouse 只在构建期挂载）")


def assert_resolvable(pattern, label):
    """ldd 一遍：任何 `not found` 都说明自包含化失败。"""
    paths = sorted(glob.glob(pattern))
    assert paths, "%s 没有匹配到 .so（%s）" % (label, pattern)
    bad = []
    for path in paths:
        out = subprocess.run(["ldd", path], capture_output=True, text=True).stdout
        if "not found" in out:
            bad.append("%s:\n%s" % (path, out))
    assert not bad, "以下 %s 存在未解析的动态依赖:\n%s" % (label, "\n".join(bad))
    print("%s：%d 个 .so 的动态依赖全部可解析" % (label, len(paths)))


def check_pillow():
    """Pillow 自编译契约：版本、格式矩阵、绝不链 libimagequant。"""
    from PIL import Image, features

    major = int(Image.__version__.split(".")[0])
    assert major >= 13, "Pillow 版本过低（%s），解码器 CVE 修复需要 13.x" % Image.__version__

    for fmt in ("jpg", "zlib", "webp"):
        assert features.check(fmt), "Pillow 缺少 %s 支持（验证码常见格式）" % fmt

    assert not features.check("libimagequant"), (
        "Pillow 链上了 libimagequant（GPL-3.0）：构建期不该装 libimagequant-dev"
    )

    img = Image.new("RGB", (120, 40), "white")
    for fmt in ("PNG", "JPEG", "WEBP"):
        buf = io.BytesIO()
        img.save(buf, fmt)
        buf.seek(0)
        with Image.open(buf) as back:
            back.load()      # 触发解码
            assert back.size == (120, 40), "%s 往返尺寸不一致：%s" % (fmt, back.size)

    print("Pillow %s | jpg/zlib/webp 可用 | 无 libimagequant | 编解码往返 OK" % Image.__version__)


def check_protobuf_bundled():
    """libprotobuf-lite 必须由 onnxruntime wheel 自带，系统里不该再有 apk 版。"""
    libs = sorted(glob.glob(os.path.join(site_packages(), "onnxruntime.libs", "libprotobuf-lite*")))
    assert libs, "onnxruntime.libs/ 里没有 libprotobuf-lite —— onnxruntime wheel 不自包含"
    system = glob.glob("/usr/lib/libprotobuf-lite.so*") + glob.glob("/lib/libprotobuf-lite.so*")
    assert not system, "系统里还有 apk 装的 libprotobuf-lite: %s（应改由 wheel 提供）" % system
    print("libprotobuf-lite 由 wheel 提供：%s" % ", ".join(os.path.basename(p) for p in libs))


def check_ocr(expected_version):
    """完整 OCR 平台：依赖 → 模型加载 → 图像编码 → ONNX 前向 → 解码输出。"""
    import cv2
    import ddddocr
    import numpy as np
    import onnxruntime

    version = importlib.metadata.version("ddddocr")
    assert version == expected_version, (
        "ddddocr 版本不符：%s != %s（构建参数与冒烟参数不一致？）" % (version, expected_version)
    )
    print("ddddocr %s | cv2 %s | numpy %s | onnxruntime %s"
          % (version, cv2.__version__, np.__version__, onnxruntime.__version__))

    # 合成一张 120x40 的白底验证码图，不依赖任何外部素材
    img = np.full((40, 120, 3), 255, dtype=np.uint8)
    cv2.putText(img, "AB12", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    data = cv2.imencode(".png", img)[1].tobytes()

    # ddddocr 1.6.x 按功能分类型实例化：默认 ocr=True 是验证码分类；
    # det=True 才是目标检测模式（OCR 类型实例调 detection() 会抛 DDDDOCRError）
    text = ddddocr.DdddOcr(show_ad=False).classification(data)
    boxes = ddddocr.DdddOcr(det=True, show_ad=False).detection(data)

    assert isinstance(text, str), "classification 返回类型异常: %r" % (type(text),)
    assert 1 <= len(text) <= 6, "classification 输出长度异常: %r" % (text,)
    assert isinstance(boxes, list), "detection 返回类型异常: %r" % (type(boxes),)

    print("classification: %r | detection: %d 个候选框" % (text, len(boxes)))


def main(argv):
    platform_name = argv[1] if len(argv) > 1 else ""
    expected_version = argv[2] if len(argv) > 2 else ""
    if not platform_name or not expected_version:
        raise SystemExit(
            "用法: python3 - <platform> <ddddocr 版本> < tests/smoke.py"
            "，例如 python3 - linux/arm64 1.6.1 < tests/smoke.py"
        )

    print("== 环境 ==")
    print("python %s | %s | %s" % (platform.python_version(), platform.machine(), sys.platform))

    print("== 无 wheel 残留 ==")
    check_no_wheel_leftovers()

    print("== Pillow ==")
    check_pillow()
    assert_resolvable(os.path.join(site_packages(), "PIL", "_imaging*.so"), "PIL 扩展")

    print("== OpenCV ==")
    assert_resolvable(os.path.join(site_packages(), "cv2*.so"), "cv2 扩展")

    print("== protobuf ==")
    check_protobuf_bundled()

    print("== 产物架构 ==")
    check_arch(platform_name, [
        os.path.join(site_packages(), "cv2*.so"),
        os.path.join(site_packages(), "PIL", "_imaging*.so"),
        os.path.join(site_packages(), "onnxruntime", "capi", "onnxruntime_pybind11_state.so"),
    ])

    print("== 识别链路 ==")
    check_ocr(expected_version)

    print("smoke(%s): PASS" % platform_name)


if __name__ == "__main__":
    main(sys.argv)
