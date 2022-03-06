# 基础镜像
FROM alpine:edge

# 维护者信息
LABEL maintainer "a76yyyy <q981331502@163.com>"
LABEL org.opencontainers.image.source=https://github.com/qiandao-today/ddddocr-docker

# Envirenment for onnxruntime
ENV ONNXRUNTIME_TAG=master

# 换源 & Install packages
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.ustc.edu.cn/g' /etc/apk/repositories && \
    apk update && \
    apk add --update --no-cache bash git tzdata nano openssh-client ca-certificates file python3 py3-pip py3-setuptools py3-wheel && \
    ln -s /usr/bin/python3 /usr/bin/python && \
    [[ $(getconf LONG_BIT) = "32" && -z $(file /bin/busybox | grep -i "arm") ]] && \
    { bashtmp='setarch i386 /onnxruntime/build.sh' && cxxtmp='-msse -msse2'; } || { \
    [[ -z $(file /bin/busybox | grep -i "arm") ]] && \
    { bashtmp='/onnxruntime/build.sh' && cxxtmp=''; } || \
    { [[ $(getconf LONG_BIT) = "32" ]] && \
    { bashtmp='' && cxxtmp=''; } || \
    { bashtmp='setarch arm64 /onnxruntime/build.sh' && cxxtmp='-Wno-psabi'; }; }; } && {\
    [[ -n "$bashtmp" ]] && { \
    apk add --update --no-cache py3-numpy-dev py3-opencv py3-pillow && {\
    apk add --update --no-cache --virtual .build_deps cmake make perl autoconf g++ automake linux-headers libtool util-linux libexecinfo-dev openblas-dev python3-dev protobuf-dev flatbuffers-dev date-dev gtest-dev eigen-dev || \
    apk add --update --no-cache --virtual .build_deps cmake make perl autoconf g++ automake linux-headers libtool util-linux libexecinfo-dev openblas-dev python3-dev protobuf-dev date-dev gtest-dev eigen-dev ;} && \
    echo $bashtmp && echo $cxxtmp && \
    git clone --depth 1 --branch $ONNXRUNTIME_TAG https://github.com/Microsoft/onnxruntime && \
    cd /onnxruntime && \
    git submodule update --init --recursive && \
    cd .. && \
    rm /onnxruntime/onnxruntime/test/providers/cpu/nn/string_normalizer_test.cc && \
    sed "s/    return filters/    filters += \[\'^test_strnorm.*\'\]\n    return filters/" -i /onnxruntime/onnxruntime/test/python/onnx_backend_test_series.py && \
    echo 'add_subdirectory(${PROJECT_SOURCE_DIR}/external/nsync EXCLUDE_FROM_ALL)' >> /onnxruntime/cmake/CMakeLists.txt && \
    $bashtmp --config MinSizeRel  \
    --parallel \
    --build_wheel \
    --enable_pybind \
    --cmake_extra_defines \
    CMAKE_CXX_FLAGS="-Wno-deprecated-copy -Wno-unused-variable $cxxtmp"\
    onnxruntime_BUILD_UNIT_TESTS=OFF \
    onnxruntime_BUILD_SHARED_LIB=OFF \
    onnxruntime_USE_PREINSTALLED_EIGEN=ON \
    onnxruntime_PREFER_SYSTEM_LIB=ON \
    eigen_SOURCE_PATH=/usr/include/eigen3 \
    --skip_tests && \
    apk del .build_deps && \
    apk add --update --no-cache libprotobuf-lite && \
    pip install --no-cache-dir /onnxruntime/build/Linux/MinSizeRel/dist/onnxruntime*.whl && \
    ln -s $(python -c 'import warnings;warnings.filterwarnings("ignore");\
    from distutils.sysconfig import get_python_lib;print(get_python_lib())')/onnxruntime/capi/libonnxruntime_providers_shared.so /usr/lib && \
    cd / && rm -rf /onnxruntime;} ;} || { \
    apk add --update --no-cache libprotobuf-lite && \
    echo "Onnxruntime Builder does not currently support building arm32 wheels";} && \
    rm -rf /var/cache/apk/* && \
    rm -rf /usr/share/man/* 