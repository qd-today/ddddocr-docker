# syntax=docker/dockerfile:1.7
#
# ddddocr 运行栈 -> musllinux wheelhouse（+ 可运行镜像）
#
# 三个出口：
#   build   ：编译 OpenCV / Pillow，打好三个 wheel，产出 /wheels（不对外）
#   wheel   ：`FROM scratch` + /wheels，只做 wheel 载体（CI 发成 <ver>-wheelhouse）
#   runtime ：alpine + python3 + 从 wheelhouse 装的包，可直接运行，里面**没有** /wheels
#
# wheelhouse 契约（/wheels）：
#   opencv-<ver>-cpXXX-cpXXX-musllinux_1_2_<arch>.whl
#   pillow-<ver>-cpXXX-cpXXX-musllinux_1_2_<arch>.whl
#   ddddocr-<ver>-py3-none-any.whl          # 纯 python + 85MB 模型文件，与架构无关
#   SHA256SUMS / system-packages.txt / simple/
#
# 三个包各自解决的问题：
#   * opencv —— apk 的 py3-opencv 会拖进 Qt6 / OpenGL / FFmpeg（约 236MB），PyPI 也没有
#     musllinux 轮子，所以自编最小化版本（core / imgproc / imgcodecs + Python 绑定）。
#   * Pillow —— Alpine 3.24 只有 12.2.0，JPEG/TIFF/FPX 解码的 5 条堆溢出要 13.0.0 才修；
#     且 apk 的 py3-pillow 链了 GPL-3.0 的 libimagequant，自编时不给 libimagequant-dev
#     就不会链上（Pillow 本体是 MIT-CMU）。
#   * onnxruntime / numpy —— 不在本仓库编译，取自 a76yyyy/onnxruntime:<ver>-wheelhouse
#     （bind mount 其 /wheels）。libprotobuf-lite 已 bundle 在 onnxruntime.libs/ 里，
#     所以不再 apk add。
#
# 用法：
#   docker buildx build --platform linux/arm64 --target wheel --output type=local,dest=./dist .
#   docker buildx build --platform linux/arm64 --target runtime -t ddddocr:test .

ARG ALPINE_VERSION=3.24
# loong64 没有官方 alpine 镜像，得走 ghcr.io/loong64/alpine，所以基座做成参数
ARG BASE_IMAGE=alpine:${ALPINE_VERSION}
# onnxruntime / numpy 的来源（同仓库另一条流水线的产物）
ARG ONNX_WHEELHOUSE=a76yyyy/onnxruntime:1.24.4-wheelhouse

########################################################################
# 外来的 wheelhouse：只是把 /wheels 借给下面两个阶段用
########################################################################
FROM ${ONNX_WHEELHOUSE} AS onnx-wheelhouse

########################################################################
# 构建：编译 OpenCV / Pillow，打 wheel
########################################################################
FROM ${BASE_IMAGE} AS build

ARG APK_MIRROR=""
ARG PIP_MIRROR=""
ARG GIT_DOMAIN=https://github.com
ARG DDDDOCR_REF=master
ARG DDDDOCR_VERSION=""
ARG OPENCV_VERSION=4.14.0
# OpenCV 的 CPU 基线优化开关（opt-in，留空 = OpenCV 默认行为）。
# 仅 armv7 有意义：ARM32 上 NEON 是可选扩展，OpenCV 默认不启用（Baseline 为空）。
ARG OPENCV_CPU_BASELINE=""
ARG PILLOW_VERSION=13.0.0
ARG NUMPY_VERSION=2.4.6
ARG AUDITWHEEL_VERSION=6.8.2
ARG TARGETARCH

LABEL maintainer="a76yyyy <q981331502@163.com>"
LABEL org.opencontainers.image.source=https://github.com/qd-today/ddddocr-docker

# 镜像源（国内构建用）：把 APK_MIRROR 末尾的 / 去掉后整体替换 host
RUN if [ -n "${APK_MIRROR}" ]; then \
        sed -i "s|https://dl-cdn.alpinelinux.org|${APK_MIRROR%/}|g" /etc/apk/repositories; \
    fi \
 && cat /etc/apk/repositories

# 编译期依赖：
#   cmake/build-base/python3-dev —— OpenCV 与 Pillow 的编译
#   libjpeg-turbo-dev/libpng-dev/zlib-dev/libwebp-dev —— 两者共用的编解码器（同一个库
#     只装一份，auditwheel 会把它们分别收进 opencv.libs/ 与 pillow.libs/）
#   patchelf/binutils —— auditwheel 改 RPATH 与 readelf 判定依赖
#   py3-pip/py3-setuptools/py3-wheel —— 打 wheel 与跑 auditwheel
RUN apk add --no-cache \
        binutils \
        build-base \
        cmake \
        git \
        libjpeg-turbo-dev \
        libpng-dev \
        libwebp-dev \
        linux-headers \
        patchelf \
        py3-pip \
        py3-setuptools \
        py3-wheel \
        python3-dev \
        zlib-dev

RUN set -eux; \
    if [ -n "${PIP_MIRROR}" ]; then pip_args="-i ${PIP_MIRROR}"; else pip_args=""; fi; \
    python3 -m pip install --no-cache-dir --break-system-packages \
        ${pip_args} "auditwheel==${AUDITWHEEL_VERSION}"; \
    python3 -m auditwheel --version

# OpenCV 的 cmake 要用 numpy 的头文件，所以构建期也得有 numpy。它和运行期同源：
# 从 onnxruntime 的 wheelhouse 取（六个架构都有 musllinux 轮子，PyPI 没有）。
RUN --mount=type=bind,from=onnx-wheelhouse,source=/wheels,target=/onnx-wheels \
    python3 -m pip install --no-cache-dir --break-system-packages \
        --no-index --find-links /onnx-wheels "numpy==${NUMPY_VERSION}" \
 && python3 -c "import numpy; print('numpy', numpy.__version__, numpy.get_include())"

# ---- OpenCV ----------------------------------------------------------------
RUN set -eux; \
    wget -q -O /tmp/opencv.tar.gz \
        "https://github.com/opencv/opencv/archive/refs/tags/${OPENCV_VERSION}.tar.gz"; \
    tar -C /tmp -xzf /tmp/opencv.tar.gz; \
    rm -f /tmp/opencv.tar.gz

# OpenCV 的目标架构必须显式指定，不能让 cmake 从 uname 推断：
# 在 GitHub 原生 arm64 runner 上，armv7 容器由内核 compat 模式直接执行（不经 QEMU），
# uname -m 返回 aarch64 -> cmake 走进 AARCH64 分支，用 aarch64 的检查文件喂 arm32
# 编译器，还按 AArch64 配置 NEON_DOTPROD/NEON_BF16 等无效 dispatch。构建能过、冒烟
# 也过，配置却是错的。给 cmake 一个「说真话的 uname」（-DCMAKE_UNAME）只影响这一次
# configure，不像改 PATH 那样波及后续的 apk/pip。
#
# -DCMAKE_INSTALL_RPATH：`libopencv_*.so` 装在 /opt/opencv/lib，不在 musl 的默认搜索
# 路径上；auditwheel 靠 RPATH 才能定位它们，之后再改写成 $ORIGIN + $ORIGIN/opencv.libs。
#
# 两条断言盯住「架构探测到了正确的处理器」：
#   1) cmake 打印的 Detected processor 必须等于预期（armv7 下应匹配到 armv7l）
#   2) 走对 ARM32 分支后，不应再出现 AArch64 专属的 dispatch 探测（NEON_DOTPROD /
#      NEON_BF16 只在 AARCH64 分支里定义）
RUN set -eux; \
    cmake_baseline=""; \
    if [ -n "${OPENCV_CPU_BASELINE}" ]; then \
        cmake_baseline="-DCPU_BASELINE=${OPENCV_CPU_BASELINE}"; \
    fi; \
    cmake_uname=""; \
    if [ "$TARGETARCH" = "arm" ]; then \
        mkdir -p /tmp/uname-shim; \
        printf '#!/bin/sh\n[ "$1" = "-m" ] && { echo armv7l; exit 0; }\nexec /bin/busybox uname "$@"\n' > /tmp/uname-shim/uname; \
        chmod +x /tmp/uname-shim/uname; \
        cmake_uname="-DCMAKE_UNAME=/tmp/uname-shim/uname"; \
    fi; \
    case "${TARGETARCH}" in \
        amd64)   cmake_proc=x86_64 ;; \
        arm64)   cmake_proc=aarch64 ;; \
        arm)     cmake_proc=arm ;; \
        ppc64le) cmake_proc=ppc64le ;; \
        riscv64) cmake_proc=riscv64 ;; \
        loong64) cmake_proc=loongarch64 ;; \
        *) echo "错误: 未知 TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    cmake -S "/tmp/opencv-${OPENCV_VERSION}" -B /tmp/opencv-build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/opt/opencv \
        -DCMAKE_INSTALL_RPATH=/opt/opencv/lib \
        -DCMAKE_SYSTEM_PROCESSOR="${cmake_proc}" ${cmake_uname} ${cmake_baseline} \
        -DBUILD_LIST=core,imgproc,imgcodecs,python3 \
        -DBUILD_SHARED_LIBS=ON \
        -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_opencv_apps=OFF \
        -DWITH_QT=OFF -DWITH_GTK=OFF -DWITH_OPENGL=OFF -DWITH_FFMPEG=OFF \
        -DWITH_IPP=OFF -DWITH_TBB=OFF -DWITH_OPENCL=OFF -DWITH_CUDA=OFF -DWITH_V4L=OFF \
        -DBUILD_opencv_python3=ON > /tmp/cmake.log 2>&1 || \
        { echo "错误: cmake configure 失败"; tail -80 /tmp/cmake.log; exit 1; }; \
    grep -E "Detected processor|CPU/HW features|Baseline" /tmp/cmake.log; \
    grep -q "Detected processor: ${cmake_proc}" /tmp/cmake.log || \
        { echo "错误: cmake 探测到的主机架构与目标 ${cmake_proc} 不一致"; \
          grep "Detected processor" /tmp/cmake.log; exit 1; }; \
    if [ "$TARGETARCH" = "arm" ]; then \
        ! grep -qE "NEON_DOTPROD|NEON_BF16" /tmp/cmake.log || \
            { echo "错误: armv7 构建仍带 AArch64 专属 dispatch，架构判定有误"; exit 1; }; \
    fi; \
    cmake --build /tmp/opencv-build -j"$(nproc)"; \
    cmake --install /tmp/opencv-build; \
    rm -rf /opt/opencv/share /opt/opencv/include; \
    find /opt/opencv -name '*.so*' -exec strip --strip-unneeded {} + 2>/dev/null || true; \
    rm -rf /tmp/uname-shim /tmp/cmake.log /tmp/opencv-build "/tmp/opencv-${OPENCV_VERSION}"


# ---- Pillow ----------------------------------------------------------------
# --no-binary 强制从源码构建：build_deps 里没有 libimagequant-dev，就不会像 Alpine 的
# py3-pillow 那样链上 GPL-3.0 的 libimagequant。只开验证码用得到的格式（jpeg/png/webp），
# 不装 tiff/freetype/lcms2。
#
# 用默认的 build isolation：Pillow 13 的构建后端依赖 pybind11，装在隔离环境里比往镜像
# 里塞一份编译期依赖干净（镜像里那套是给 auditwheel 用的，与 Pillow 无关）。
RUN set -eux; \
    case "${TARGETARCH}" in \
        amd64|arm64|arm|ppc64le|riscv64|loong64) : ;; \
        *) echo "错误: 未知 TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    if [ -n "${PIP_MIRROR}" ]; then pip_args="--index-url ${PIP_MIRROR}"; else pip_args=""; fi; \
    python3 -m pip wheel ${pip_args} --no-cache-dir \
        --no-binary :all: --no-deps \
        --wheel-dir /tmp/pillow-wheel "pillow==${PILLOW_VERSION}"; \
    ls -l /tmp/pillow-wheel

# ---- ddddocr 源码 ----------------------------------------------------------
# 支持 分支名/tag/SHA。tag 发布时 CI 传 ddddocr.version 里锁定的 commit（可复现），
# 其余情况跟随上游 master。
RUN set -eux; \
    mkdir -p /src; \
    git init -q /src/ddddocr; \
    cd /src/ddddocr; \
    git remote add origin "${GIT_DOMAIN}/sml2h3/ddddocr.git"; \
    git fetch --depth 1 -q origin "${DDDDOCR_REF}"; \
    git checkout -q FETCH_HEAD; \
    git rev-parse HEAD

COPY src/pack_wheel.py /usr/local/bin/pack_wheel.py
# 系统包清单随 wheelhouse 一起发布：上层照单 apk add 即可，不必各自维护
COPY system-packages.txt /wheels/system-packages.txt

RUN set -eux; \
    python3 /usr/local/bin/pack_wheel.py --opencv /opt/opencv \
        --version "${OPENCV_VERSION}" --out-dir /wheels; \
    python3 /usr/local/bin/pack_wheel.py \
        --repair "$(ls /tmp/pillow-wheel/pillow-*.whl)" --out-dir /wheels; \
    python3 /usr/local/bin/pack_wheel.py --ddddocr /src/ddddocr \
        --expect-version "${DDDDOCR_VERSION}" --out-dir /wheels; \
    python3 /usr/local/bin/pack_wheel.py --emit-index --out-dir /wheels; \
    cd /wheels; \
    ls -l; \
    sha256sum ./*.whl > SHA256SUMS; \
    cat SHA256SUMS

########################################################################
# wheel 出口：只有 /wheels（CI 用 --output type=local 取出，或打成 <ver>-wheelhouse）
########################################################################
FROM scratch AS wheel

COPY --from=build /wheels/ /wheels/

########################################################################
# 运行时出口
#
# 为什么不用 `COPY --from=build /wheels /wheels` + `RUN rm -rf /wheels`：COPY 和 RUN
# 是两层，删掉的字节仍在下面那层里，镜像照样算进去（这里是 ~87MB 白花）。用 BuildKit
# 的 bind mount 把 wheelhouse 只挂进这两条 RUN，装完即随 layer 消失，镜像里没有 /wheels。
########################################################################
FROM ${BASE_IMAGE} AS runtime

ARG APK_MIRROR=""
ARG PIP_MIRROR=""
ARG ONNX_VERSION=1.24.4
ARG NUMPY_VERSION=2.4.6
ARG OPENCV_VERSION=4.14.0
ARG PILLOW_VERSION=13.0.0
ARG DDDDOCR_VERSION=""

LABEL maintainer="a76yyyy <q981331502@163.com>"
LABEL org.opencontainers.image.source=https://github.com/qd-today/ddddocr-docker

RUN if [ -n "${APK_MIRROR}" ]; then \
        sed -i "s|https://dl-cdn.alpinelinux.org|${APK_MIRROR%/}|g" /etc/apk/repositories; \
    fi \
 && cat /etc/apk/repositories

# 系统包按 wheelhouse 里的清单装（清单写错会在这里构建失败，不会等到上层才发现）。
# 清单只有 wheel 真正的运行时依赖：解释器 python3 + libz（musllinux 白名单里只有
# libc 与 libz，所以 libz 不会被打进 .libs，而 PIL 与 libopencv_imgcodecs 都链了它）。
# bash / tzdata / ca-certificates / icu-data-en 是本镜像自带的便利项，不属于 wheel
# 契约，所以不写进清单：icu-data-en 是 onnxruntime 的 libicu 数据文件（ddddocr 的
# 图像模型用不到，但上层若有字符串算子会需要）。
# uv 是包管理器（python3 不含 pip），也只是工具，不是运行时依赖。
RUN --mount=type=bind,from=build,source=/wheels,target=/w \
    apk add --no-cache $(cat /w/system-packages.txt) bash ca-certificates icu-data-en tzdata uv

# 装包分两步，原因是索引优先级不可依赖：
#
# 1) 本仓库和 onnxruntime 的 wheelhouse 里的五个包，**只**从本地取（--no-index）。
#    不加 --no-index 的话，uv 会把 PyPI 上的同名包排在 file:// 索引之前 —— ddddocr /
#    Pillow / numpy / onnxruntime 在 PyPI 上都有同版本文件，实测即使
#    `--index-strategy first-index` 也照样选中 PyPI 那份；而 PyPI 的 ddddocr 元数据要求
#    `opencv-python-headless`，musl 上没有轮子，构建会退化成源码编译并失败。加 --no-index
#    后「这五个包一定来自 wheelhouse」是可验证的事实，而不是靠索引顺序的巧合。
#    --no-deps 只装 wheel 本体，传递依赖交给下一步。
# 2) onnxruntime / ddddocr 剩下的传递依赖（flatbuffers / packaging / protobuf / sympy）
#    是纯 python 轮子，各架构都有，走 PyPI。清单写死是有意的：`uv pip check` 会在下一步
#    立刻断言「依赖是否齐全」，上游加了依赖而清单没跟上就直接让构建失败。
#
# `--no-cache` 不是省事，是必须：uv 默认把解压后的包再存一份到 /root/.cache/uv，会原样
# 进镜像层（实测多出 130MB）。
#
# 清理 sympy / mpmath：onnxruntime 只用它们做符号形状推断，ddddocr 不用。放在同一条
# RUN 里删，才不会被下面那层留住。
RUN --mount=type=bind,from=build,source=/wheels,target=/wheels \
    --mount=type=bind,from=onnx-wheelhouse,source=/wheels,target=/w \
    set -eux; \
    ddddocr_req="ddddocr"; \
    if [ -n "${DDDDOCR_VERSION}" ]; then ddddocr_req="ddddocr==${DDDDOCR_VERSION}"; fi; \
    pypi="${PIP_MIRROR:-https://pypi.org/simple}"; \
    uv pip install --system --break-system-packages --no-cache --no-deps \
        --no-index --find-links /wheels --find-links /w \
        "${ddddocr_req}" \
        "opencv==${OPENCV_VERSION}" \
        "pillow==${PILLOW_VERSION}" \
        "onnxruntime==${ONNX_VERSION}" \
        "numpy==${NUMPY_VERSION}"; \
    uv pip install --system --break-system-packages --no-cache \
        --index-url "${pypi}" flatbuffers packaging protobuf sympy; \
    uv pip check --system; \
    site="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"; \
    rm -rf "${site}"/sympy* "${site}"/mpmath* "${site}"/isympy.py "${site}"/numpy/tests; \
    rm -rf /root/.cache/uv /tmp/uv-*; \
    python3 -c "import ddddocr, cv2, onnxruntime, numpy; \
print('cv2', cv2.__version__, '| onnxruntime', onnxruntime.__version__, '| numpy', numpy.__version__)"

# runtime 是给上层 FROM 的基座；`docker run <image>` 打一次自检
CMD ["python3", "-c", "import ddddocr, cv2, onnxruntime; print('ddddocr ready | cv2', cv2.__version__, '| onnxruntime', onnxruntime.__version__)"]
