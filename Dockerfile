# 基础镜像
FROM alpine:edge

# 维护者信息
LABEL maintainer "a76yyyy <q981331502@163.com>"
LABEL org.opencontainers.image.source=https://github.com/qd-today/ddddocr-docker

ARG TARGETARCH
# ENV TARGETARCH=${TARGETARCH}

# Envirenment for dddocr
ARG DDDDOCR_VERSION=master
# ENV DDDDOCR_VERSION=${DDDDOCR_VERSION}

# 换源 & Install packages
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.ustc.edu.cn/g' /etc/apk/repositories && \
    echo 'https://mirrors.ustc.edu.cn/alpine/edge/testing' >> /etc/apk/repositories && \
    apk update && \
    apk add --update --no-cache bash git tzdata ca-certificates file python3 py3-six && \
    # ln -s /usr/bin/python3 /usr/bin/python && \
    [[ "${TARGETARCH}" != "i386" ]] && [[ "${TARGETARCH}" != "s390x" ]] && { \
    apk add --update --no-cache py3-pillow py3-onnxruntime py3-opencv libprotobuf-lite && \
    apk add --update --no-cache --virtual .build_deps py3-pip py3-setuptools py3-wheel protobuf-dev py3-numpy-dev \
        lld samurai build-base gcc python3-dev musl-dev linux-headers make && \
    git clone --branch $DDDDOCR_VERSION https://github.com/sml2h3/ddddocr.git && \
    cd /ddddocr && \
    sed -i '/install_package_data/d' setup.py && \
    sed -i '/install_requires/d' setup.py && \
    sed -i '/python_requires/d' setup.py && \
    pip install --no-cache-dir --compile . && \
    cd / && rm -rf /ddddocr && \
    apk del .build_deps; \
    } || { \
    apk add --update --no-cache libprotobuf-lite && \
    echo "Onnxruntime Builder does not currently support building i386 and s390x wheels";} && \
    rm -rf /var/cache/apk/* && \
    rm -rf /usr/share/man/*
