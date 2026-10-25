#!/usr/bin/env python3
"""OCR 链路性能基准：量化「OpenCV 是否启用 NEON」的差异。

容器内以 stdin 执行（无需把脚本塞进镜像）：

    docker run --rm -i --platform linux/arm/v7 <image> python3 - < tests/bench.py

设计要点：
- 分三组测量，才能看清 NEON 到底加速了链条的哪一段：
    1) 纯 OpenCV 预处理（resize / cvtColor / GaussianBlur / threshold）
    2) 纯 onnxruntime 推理（classification / detection）
    3) 端到端（解码 + 预处理 + 推理），即真实一次识别的开销
- 固定随机种子、先预热、取中位数，避免抖动影响结论
- 不做绝对性能断言（不同机器差异太大）：只打印数字与构建信息，供横向对比
- BENCH_ITERS 可调（默认 30），QEMU 环境下建议调小
"""

import os
import platform
import statistics
import sys
import time

import cv2
import ddddocr
import numpy as np
import onnxruntime

ITERS = int(os.environ.get("BENCH_ITERS", "30"))
RESULTS = {}


def bench(label, fn, iters=ITERS):
    fn()  # 预热一次，排除首次调用的页错误/惰性初始化
    samples = []
    for _ in range(iters):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    samples.sort()
    median = statistics.median(samples)
    print("%-30s %9.2f ms   (min %7.2f / p90 %7.2f)"
          % (label, median, samples[0], samples[min(iters - 1, int(iters * 0.9))]))
    RESULTS[label] = median
    return median


def build_baseline():
    """从 cv2.getBuildInformation() 里抠出 CPU 基线，用于确认两版镜像确实不同。"""
    for line in cv2.getBuildInformation().splitlines():
        if "Baseline:" in line or "Dispatched:" in line:
            return line.strip()
    return "<未找到>"


def main():
    print("python %s | %s | numpy %s | onnxruntime %s"
          % (platform.python_version(), platform.machine(),
             np.__version__, onnxruntime.__version__))
    print("OpenCV %s | %s" % (cv2.__version__, build_baseline()))
    print("iters=%d" % ITERS)
    print()

    rng = np.random.default_rng(20261025)
    # 640x480 的合成图：噪声 + 文字，兼顾内存带宽与运算量
    frame = rng.integers(0, 256, size=(480, 640, 3), dtype=np.uint8)
    cv2.putText(frame, "A1B2C3", (40, 240), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 3)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    print("== 1. 纯 OpenCV 预处理（640x480）==")
    bench("resize 640x480 -> 320x240", lambda: cv2.resize(frame, (320, 240)))
    bench("cvtColor BGR2GRAY", lambda: cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    bench("GaussianBlur 5x5", lambda: cv2.GaussianBlur(frame, (5, 5), 0))
    bench("threshold", lambda: cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY))
    bench("preprocess 组合（resize+gray+blur）",
          lambda: cv2.GaussianBlur(cv2.cvtColor(cv2.resize(frame, (320, 240)),
                                                cv2.COLOR_BGR2GRAY), (5, 5), 0))

    # 一张典型验证码：120x40 白底黑字
    captcha = np.full((40, 120, 3), 255, dtype=np.uint8)
    cv2.putText(captcha, "AB12", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
    _, encoded = cv2.imencode(".png", captcha)
    payload = encoded.tobytes()

    ocr = ddddocr.DdddOcr(show_ad=False)
    det = ddddocr.DdddOcr(det=True, show_ad=False)

    print()
    print("== 2. onnxruntime 推理（不受 OpenCV NEON 影响，作为对照）==")
    bench("classification (120x40)", lambda: ocr.classification(payload))
    bench("detection (120x40)", lambda: det.detection(payload))

    print()
    print("== 3. 端到端：解码 + 预处理 + 推理 ==")

    def end_to_end():
        array = np.frombuffer(payload, dtype=np.uint8)
        img = cv2.imdecode(array, cv2.IMREAD_COLOR)
        cv2.resize(img, (160, 60))
        cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return ocr.classification(payload)

    bench("imdecode + resize + gray + classify", end_to_end)

    print()
    cv_pre = sum(RESULTS[k] for k in RESULTS if k not in
                 ("classification (120x40)", "detection (120x40)",
                  "imdecode + resize + gray + classify"))
    infer = RESULTS["classification (120x40)"]
    print("汇总：OpenCV 处理 %.2f ms | classification 推理 %.2f ms | 端到端 %.2f ms"
          % (cv_pre, infer, RESULTS["imdecode + resize + gray + classify"]))


if __name__ == "__main__":
    sys.exit(main())
