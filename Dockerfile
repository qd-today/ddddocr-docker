# 基础镜像
FROM alpine:edge

# 维护者信息
LABEL maintainer "a76yyyy <q981331502@163.com>"
LABEL org.opencontainers.image.source=https://github.com/qiandao-today/ddddocr-docker

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
    apk add --update --no-cache py3-pillow py3-onnxruntime py3-numpy libtbb \
    libjpeg libpng tiff libwebp openjpeg openjpeg-tools eigen blas && \
    apk add --update --no-cache --virtual .build_deps py3-pip py3-setuptools py3-wheel protobuf-dev py3-numpy-dev \
        clang cmake lld samurai build-base gcc python3-dev musl-dev libffi-dev g++ linux-headers make libva-glx-dev \
        openblas-dev libjpeg-turbo-dev libpng-dev tiff-dev libwebp-dev openjpeg-dev libtbb-dev eigen-dev blas-dev && \
    mkdir opencv && cd opencv && \
    git clone https://ghproxy.com/https://github.com/opencv/opencv.git && \
    [[ "${TARGETARCH}" == "amd64" ]] && \
        extra_cmake_flags="-D CPU_BASELINE_DISABLE=SSE3 -D CPU_BASELINE_REQUIRE=SSE2" || extra_cmake_flags="" && \
    CC=clang CXX=clang++ \
    cmake -B build -G Ninja \
        -D CMAKE_BUILD_TYPE=RELEASE \
        -D CMAKE_INSTALL_PREFIX=/usr \
        -D CMAKE_INSTALL_LIBDIR=lib \
        -D CMAKE_SKIP_INSTALL_RPATH=ON \
        -D ENABLE_BUILD_HARDENING=ON \
        -D EIGEN_INCLUDE_PATH=/usr/include/eigen3 \
        -D OPENCV_ENABLE_NONFREE=OFF \
        -D OPENCV_SKIP_PYTHON_LOADER=ON \
        -D OPENCV_GENERATE_SETUPVARS=OFF \
        -D WITH_JPEG=ON \
        -D WITH_PNG=ON \
        -D WITH_TIFF=ON \
        -D WITH_WEBP=ON \
        -D WITH_JASPER=ON \
        -D WITH_EIGEN=ON \
        -D WITH_TBB=ON \
        -D WITH_LAPACK=ON \
        -D WITH_PROTOBUF=ON \
        -D WITH_ADE=OFF \
        -D WITH_V4L=OFF \
        -D WITH_GSTREAMER=OFF \
        -D WITH_GTK=OFF \
        -D WITH_QT=OFF \
        -D WITH_CUDA=OFF \
        -D WITH_VTK=OFF \
        -D WITH_OPENEXR=OFF \
        -D WITH_FFMPEG=OFF \
        -D WITH_OPENCL=OFF \
        -D WITH_OPENNI=OFF \
        -D WITH_XINE=OFF \
        -D WITH_GDAL=OFF \
        -D WITH_IPP=OFF \
        -D WITH_opencv_gapi=OFF \
        -D WITH_IPP=OFF \
        -D BUILD_OPENCV_PYTHON3=ON \
        -D BUILD_OPENCV_PYTHON2=OFF \
        -D BUILD_OPENCV_JAVA=OFF \
        -D BUILD_TESTS=OFF \
        -D BUILD_IPP_IW=OFF \
        -D BUILD_PERF_TESTS=OFF \
        -D BUILD_EXAMPLES=OFF \
        -D BUILD_ANDROID_EXAMPLES=OFF \
        -D BUILD_DOCS=OFF \
        -D BUILD_ITT=OFF \
        -D INSTALL_PYTHON_EXAMPLES=OFF \
        -D INSTALL_C_EXAMPLES=OFF \
        -D INSTALL_TESTS=OFF \
        -D PYTHON3_EXECUTABLE=/usr/bin/python3 \
        -D PYTHON3_INCLUDE_DIR=$(python -c "from sysconfig import get_paths as gp; print(gp()['include'])") \
        -D PYTHON3_LIBRARY=/usr/lib/libpython3.so \
        -D PYTHON3_PACKAGES_PATH=$(python -c "from sysconfig import get_paths as gp; print(gp()['purelib'])") \
        -D PYTHON3_NUMPY_INCLUDE_DIRS=$(python -c "from sysconfig import get_paths as gp; print(gp()['purelib'])")/numpy/core/include/ \
        -D Protobuf_INCLUDE_DIR=/usr/include/google/protobuf \
        -D Protobuf_LIBRARY=/usr/lib/libprotobuf.so \
        -D Protobuf_PROTOC_EXECUTABLE=/usr/bin/protoc \
        $extra_cmake_flags \
        ./opencv \
    && cmake --build build && \
    cmake --install build && \
    cd / && rm -rf /opencv && \
    git clone --branch $DDDDOCR_VERSION https://ghproxy.com/https://github.com/sml2h3/ddddocr.git && \
    cd ddddocr && \
    sed -i '/install_package_data/d' setup.py && \
    sed -i '/install_requires/d' setup.py && \
    sed -i '/python_requires/d' setup.py && \
    pip install . && \
    cd / && rm -rf /ddddocr && \
    apk del .build_deps; \
    } || { \
    apk add --update --no-cache libprotobuf-lite && \
    echo "Onnxruntime Builder does not currently support building i386 and s390x wheels";} && \
    rm -rf /var/cache/apk/* && \
    rm -rf /usr/share/man/*