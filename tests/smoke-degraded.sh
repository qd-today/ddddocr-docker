#!/bin/sh
# 空壳镜像（linux/386、linux/arm/v6、linux/s390x）冒烟测试。
# 这三个平台缺 onnxruntime（上游不提供 i386/s390x wheel，armv6 无可用构建），
# 镜像里只有 python3 + libprotobuf-lite，没有 OpenCV、也没有 ddddocr 包本身。
# 运行方式（无需挂载）：
#   docker run --rm -i --platform <platform> <image> sh -s < tests/smoke-degraded.sh
#
# 断言的是「空壳契约」而不是「功能可用」：下面三条与 README「⚠️ 空壳镜像」
# 一节一一对应。一旦哪天上游补齐依赖、我们真的在这些平台加上 OCR 栈，
# 这里会失败并迫使同步更新文档与平台矩阵。
set -eu

echo "== 1. python3 可用 =="
python3 -c "import sys; print('python', sys.version.split()[0])"

echo "== 2. libprotobuf-lite 运行时库在位（下游 C 扩展链接目标）=="
ls /usr/lib/libprotobuf-lite.so*

echo "== 3. 确认是空壳：ddddocr / cv2 均不存在 =="
if python3 -c "import ddddocr" 2>/dev/null; then
    echo "FAIL: 该平台竟能 import ddddocr —— 若已支持 OCR，请同步更新 README 平台矩阵与本脚本"
    exit 1
fi
if python3 -c "import cv2" 2>/dev/null; then
    echo "FAIL: 该平台竟能 import cv2 —— 若已支持 OCR，请同步更新 README 平台矩阵与本脚本"
    exit 1
fi
echo "ddddocr / cv2 均不存在（符合空壳契约）"

echo
echo "smoke-degraded: ALL PASS"
