#!/usr/bin/env python3
"""ddddocr OCR 栈自检 —— 行为级验证的唯一真相源。

由 CI 的 per-arch 冒烟矩阵调用，覆盖全部 6 个 OCR 平台（amd64/arm64/armv7/
ppc64le/riscv64/loong64）。脚本不进镜像，直接 stdin 喂进去执行：

    docker run --rm -i --platform <platform> <image> python3 - < tests/ocr-selfcheck.py

验证链路：依赖 import → 模型加载 → 图像编码 → ONNX 前向 → 解码输出。
**不断言识别准确率**：合成字体与真实验证码分布不同，准确率断言会 flaky；
这里只验证「链路完整、输出结构合理」，即镜像里的 OpenCV/onnxruntime 真的能用。

为什么放在独立文件而不是 Dockerfile 内联：构建期断言应只管「产物自洽」，
行为验证属于测试阶段。写成文件后语法可 lint、可本地直接跑、也不会在
Dockerfile 里堆一段 heredoc 嵌 heredoc（曾需要专门验证嵌套是否正确）。
"""

import sys

import cv2
import ddddocr
import numpy as np
import onnxruntime


def main():
    print(
        "cv2 %s | numpy %s | onnxruntime %s"
        % (cv2.__version__, np.__version__, onnxruntime.__version__)
    )

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
    print("OCR selfcheck: PASS")


if __name__ == "__main__":
    sys.exit(main())
