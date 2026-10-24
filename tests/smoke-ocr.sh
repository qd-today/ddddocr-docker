#!/bin/sh
# ddddocr 完整 OCR 栈冒烟测试。运行方式（CI 与本地通用，无需挂载）：
#   docker run --rm -i <image> sh -s < tests/smoke-ocr.sh
# 验证点：cv2/numpy/onnxruntime/ddddocr import、DdddOcr 模型加载、
#         分类与检测推理链路（合成验证码图片，不断、输出结构合理）
#
# 说明：不断言识别准确率——合成字体与真实验证码分布有差异，准确率断言会 flaky；
# 只验证"模型加载 + 预处理 + ONNX 推理 + 解码"全链路完整可用。
set -eu

echo "== 1. import 与版本 =="
python3 -c "import cv2, numpy, onnxruntime, ddddocr; print('cv2', cv2.__version__, '| numpy', numpy.__version__, '| onnxruntime', onnxruntime.__version__)"

echo "== 2. DdddOcr 实例化（默认模型加载）=="
python3 -c "import ddddocr; ddddocr.DdddOcr(show_ad=False); print('DdddOcr 实例化 OK')"

echo "== 3. 推理链路：合成验证码分类 + 目标检测 =="
python3 - <<'EOF'
import cv2
import ddddocr
import numpy as np

img = np.full((40, 120, 3), 255, dtype=np.uint8)
cv2.putText(img, "AB12", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
_, png = cv2.imencode(".png", img)
data = png.tobytes()

# ddddocr 1.6.x 按功能分类型实例化：默认 ocr=True（旧版验证码分类）；
# det=True 才是目标检测模式（OCR 类型实例调 detection() 会抛 DDDDOCRError）
text = ddddocr.DdddOcr(show_ad=False).classification(data)
assert isinstance(text, str), f"classification 返回值类型异常: {type(text)}"
assert 1 <= len(text) <= 6, f"classification 输出长度异常: {text!r}"
print(f"classification: {text!r}")

boxes = ddddocr.DdddOcr(det=True, show_ad=False).detection(data)
assert isinstance(boxes, list), f"detection 返回值类型异常: {type(boxes)}"
print(f"detection: {len(boxes)} 个候选框")
print("推理链路 OK")
EOF

echo
echo "smoke-ocr: ALL PASS"
