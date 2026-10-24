#!/usr/bin/env python3
"""镜像冒烟测试 —— 全部平台的唯一入口，用参数显式声明「这个平台应该长什么样」。

容器内以 stdin 执行，脚本不进镜像、不加层、不依赖 bind mount：

    docker run --rm -i --platform <platform> <image> python3 - <ocr|degraded> < tests/smoke.py

    # 例如
    docker run --rm -i --platform linux/riscv64 <image> python3 - ocr < tests/smoke.py

为什么不自动探测能力、而要显式传参：自动探测（能 import ddddocr 就跑 OCR 检查）
会静默降级——万一某个 OCR 平台上的 ddddocr 意外消失，脚本会「顺滑」地改跑空壳
检查并通过，正是我们最想抓的那种回归。显式声明期望，期望与实际不符就失败。

为什么只有一个文件：OCR 平台与空壳平台检查的是同一件事的两面（「OCR 栈能真的
推理」/「这里确实没有 OCR 栈」），拆成两个文件会让公共的依赖探测、报告格式、
退出码约定各写一遍，最终必然漂移。
"""

import glob
import sys

MODES = ("ocr", "degraded")


def check_common():
    """两种镜像都必须满足的最低要求。"""
    import platform

    print("python %s | %s" % (platform.python_version(), platform.machine()))

    # libprotobuf-lite 是 onnxruntime/ddddocr 以及下游 C 扩展的运行时依赖，
    # 任何变体都必须带着它
    libs = glob.glob("/usr/lib/libprotobuf-lite.so*")
    assert libs, "libprotobuf-lite 缺失（下游 C 扩展无法链接）"
    print("libprotobuf-lite: %s" % ", ".join(sorted(libs)))


def check_degraded():
    """空壳平台契约：只有 python3 + protobuf 运行时，没有任何 OCR 能力。

    与 README「⚠️ 空壳镜像」一节一一对应。哪天上游补齐依赖、我们真的在这些
    平台加上 OCR 栈，这里会失败并迫使同步更新文档与平台矩阵。
    """
    for mod in ("ddddocr", "cv2", "onnxruntime"):
        try:
            __import__(mod)
        except ImportError:
            print("%-12s 不存在（符合空壳契约）" % mod)
        else:
            raise AssertionError(
                "%s 竟然可以 import —— 若该平台已支持 OCR，请同步更新 README 平台矩阵与本脚本" % mod
            )


def check_ocr():
    """完整 OCR 平台：依赖 → 模型加载 → 图像编码 → ONNX 前向 → 解码输出。

    不断言识别准确率：合成字体与真实验证码分布不同，准确率断言会 flaky；
    这里只验证链路完整、输出结构合理，即镜像里的 OpenCV/onnxruntime 真的能用。
    """
    import cv2
    import ddddocr
    import numpy as np
    import onnxruntime

    print("cv2 %s | numpy %s | onnxruntime %s"
          % (cv2.__version__, np.__version__, onnxruntime.__version__))

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
    mode = argv[1] if len(argv) > 1 else ""
    if mode not in MODES:
        raise SystemExit("用法: python3 - <%s> < tests/smoke.py" % "|".join(MODES))

    print("== 通用检查 ==")
    check_common()
    print("== %s 检查 ==" % mode)
    check_ocr() if mode == "ocr" else check_degraded()
    print("smoke(%s): PASS" % mode)


if __name__ == "__main__":
    main(sys.argv)
