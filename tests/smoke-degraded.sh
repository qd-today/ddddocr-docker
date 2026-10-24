#!/bin/sh
# 降级镜像（linux/386、linux/arm/v6、linux/s390x：缺 py3-onnxruntime，
# 镜像仅含 python3 + libprotobuf-lite，无 OCR 栈）冒烟测试。
# 运行方式（CI 与本地通用，无需挂载）：
#   docker run --rm -i <image> sh -s < tests/smoke-degraded.sh
set -eu

echo "== 1. python3 可用 =="
python3 -c "import sys; print('python', sys.version.split()[0])"

echo "== 2. libprotobuf-lite 运行时库在位（下游 C 扩展链接目标）=="
ls /usr/lib/libprotobuf-lite.so*

echo
echo "smoke-degraded: ALL PASS"
