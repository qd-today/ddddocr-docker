#!/usr/bin/env bash
# 把 Dockerfile 的 build-args 写进 $GITHUB_OUTPUT。
#
# build 与 smoke 两个 job 共用这一份：smoke 重建单平台镜像时 build-args 必须与 build
# 阶段逐字一致，否则 GHA 层缓存的 key 对不上，会退化成「重新编一遍 OpenCV」。
set -euo pipefail

# 只写非空项：BASE_IMAGE 为空时 `FROM ` 会直接报错
{
  echo "build_args<<__BUILD_ARGS__"
  echo "ALPINE_VERSION=${ALPINE_VERSION}"
  echo "OPENCV_VERSION=${OPENCV_VERSION}"
  echo "PILLOW_VERSION=${PILLOW_VERSION}"
  echo "ONNX_VERSION=${ONNX_VERSION}"
  echo "NUMPY_VERSION=${NUMPY_VERSION}"
  echo "ONNX_WHEELHOUSE=a76yyyy/onnxruntime:${ONNX_VERSION}-wheelhouse"
  echo "DDDDOCR_REF=${DDDDOCR_REF}"
  echo "DDDDOCR_VERSION=${DDDDOCR_VERSION}"
  echo "APK_MIRROR=${APK_MIRROR}"
  echo "PIP_MIRROR=${PIP_MIRROR}"
  if [ -n "${BASE_IMAGE:-}" ]; then
    echo "BASE_IMAGE=${BASE_IMAGE}"
  fi
  echo "__BUILD_ARGS__"
} >> "$GITHUB_OUTPUT"

echo "构建参数：alpine=${ALPINE_VERSION} opencv=${OPENCV_VERSION} pillow=${PILLOW_VERSION}"
echo "          onnxruntime=${ONNX_VERSION} numpy=${NUMPY_VERSION}"
echo "          ddddocr=${DDDDOCR_REF}@${DDDDOCR_VERSION} base=${BASE_IMAGE:-默认}"
