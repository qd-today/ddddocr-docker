# 基础镜像
FROM alpine:edge

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
echo 'https://dl-cdn.alpinelinux.org/alpine/edge/testing' >> /etc/apk/repositories
APK_CMD="apk"
if [ "x" != "x${APK_MIRROR}" ]; then
    APK_CMD="apk --repositories-file=/dev/null -X $APK_MIRROR/alpine/edge/main -X $APK_MIRROR/alpine/edge/community -X $APK_MIRROR/alpine/edge/testing"
fi
$APK_CMD update
$APK_CMD add --update --no-cache bash git tzdata ca-certificates file python3 py3-six
# ln -s /usr/bin/python3 /usr/bin/python
if [ "${TARGETPLATFORM}" = "linux/amd64" ] || [ "${TARGETPLATFORM}" = "linux/arm64" ] || [ "${TARGETPLATFORM}" = "linux/arm/v7" ]; then
    $APK_CMD add --update --no-cache py3-pillow py3-onnxruntime py3-opencv libprotobuf-lite
    $APK_CMD add --update --no-cache --virtual .build_deps py3-pip py3-setuptools py3-wheel \
        protobuf-dev py3-numpy-dev lld samurai build-base gcc python3-dev musl-dev linux-headers make
    git clone --branch $DDDDOCR_VERSION --depth 1 $GIT_DOMAIN/sml2h3/ddddocr.git
    cd /ddddocr
    sed -i '/install_package_data/d' setup.py
    sed -i '/install_requires/d' setup.py
    sed -i '/python_requires/d' setup.py
    PIP_INSTALL="pip install"
    if [ "x" != "x$PIP_MIRROR" ]; then
        PIP_INSTALL="pip install --index-url $PIP_MIRROR"
    fi
    $PIP_INSTALL --no-cache-dir --compile --break-system-packages .
    cd / && rm -rf /ddddocr
    $APK_CMD del .build_deps;
else
    $APK_CMD add --update --no-cache libprotobuf-lite
    echo "py3-pillow/py3-onnxruntime/py3-opencv does not currently support ${TARGETPLATFORM}."
fi
rm -rf /var/cache/apk/*
rm -rf /usr/share/man/*
EOT
