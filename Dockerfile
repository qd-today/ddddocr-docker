# 基础镜像
FROM alpine:3.24

# 维护者信息
LABEL maintainer "a76yyyy <q981331502@163.com>"
LABEL org.opencontainers.image.source=https://github.com/qd-today/ddddocr-docker
ARG TARGETPLATFORM

ARG APK_MIRROR=""  #e.g., https://mirrors.tuna.tsinghua.edu.cn
ARG PIP_MIRROR=""  #e.g., https://pypi.tuna.tsinghua.edu.cn/simple
ARG GIT_DOMAIN=https://github.com   #e.g., https://gh-proxy.com/https://github.com or https://gitee.com

# Envirenment for dddocr
ARG DDDDOCR_VERSION=master
# ENV DDDDOCR_VERSION=${DDDDOCR_VERSION}

# Install packages
RUN <<EOT
#!/usr/bin/env sh
set -eux
# v3.24 起 py3-onnxruntime / py3-opencv / py3-pillow / py3-numpy 均在 community 仓，无需 testing 源
APK_CMD="apk"
if [ "x" != "x${APK_MIRROR}" ]; then
    APK_CMD="apk --repositories-file=/dev/null -X $APK_MIRROR/alpine/v3.24/main -X $APK_MIRROR/alpine/v3.24/community"
fi
$APK_CMD update
$APK_CMD add --update --no-cache bash git tzdata ca-certificates file python3 py3-six
# ln -s /usr/bin/python3 /usr/bin/python
if [ "${TARGETPLATFORM}" = "linux/amd64" ] || [ "${TARGETPLATFORM}" = "linux/arm64" ] || [ "${TARGETPLATFORM}" = "linux/arm/v7" ]; then
    $APK_CMD add --update --no-cache py3-pillow py3-onnxruntime py3-opencv py3-numpy libprotobuf-lite
    # ddddocr 1.6.1 起为纯 Python 包（pyproject.toml + setuptools 后端），--no-deps 后仅需 pip/setuptools/wheel
    $APK_CMD add --update --no-cache --virtual .build_deps py3-pip py3-setuptools py3-wheel
    # 统一用 init+fetch 拉取：分支名（master）/ tag / commit SHA 均可；上游无版本 tag，发布时按 SHA 锁定
    git init -q /ddddocr
    cd /ddddocr
    git remote add origin $GIT_DOMAIN/sml2h3/ddddocr.git
    git fetch --depth 1 -q origin $DDDDOCR_VERSION
    git checkout -q FETCH_HEAD
    # 上游已无 setup.py（依赖改由 apk 预装），用 --no-deps 安装 ddddocr 本体
    PIP_INSTALL="pip install"
    if [ "x" != "x$PIP_MIRROR" ]; then
        PIP_INSTALL="pip install --index-url $PIP_MIRROR"
    fi
    $PIP_INSTALL --no-cache-dir --no-deps --compile --break-system-packages .
    # onnxruntime 的 py3-sympy 依赖仅用于符号形状推断，ddddocr 不使用；删除 sympy/mpmath 缩减镜像约 47MB
    rm -rf /usr/lib/python3.*/site-packages/sympy /usr/lib/python3.*/site-packages/mpmath
    cd / && rm -rf /ddddocr
    $APK_CMD del .build_deps;
else
    $APK_CMD add --update --no-cache libprotobuf-lite
    echo "py3-pillow/py3-onnxruntime/py3-opencv does not currently support ${TARGETPLATFORM}."
fi
rm -rf /var/cache/apk/*
rm -rf /usr/share/man/*
EOT
