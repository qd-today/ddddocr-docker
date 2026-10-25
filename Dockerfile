# 基础镜像
FROM alpine:3.24

# 维护者信息
LABEL maintainer "a76yyyy <q981331502@163.com>"
LABEL org.opencontainers.image.source=https://github.com/qd-today/ddddocr-docker
ARG TARGETPLATFORM
ARG TARGETARCH

ARG APK_MIRROR=""  #e.g., https://mirrors.tuna.tsinghua.edu.cn
ARG PIP_MIRROR=""  #e.g., https://pypi.tuna.tsinghua.edu.cn/simple
ARG GIT_DOMAIN=https://github.com   #e.g., https://gh-proxy.com/https://github.com or https://gitee.com

# Envirenment for dddocr
ARG DDDDOCR_VERSION=master
# ENV DDDDOCR_VERSION=${DDDDOCR_VERSION}
# OpenCV 源码版本：自编译最小化构建（core/imgproc/imgcodecs），替代体积臃肿的 apk py3-opencv
ARG OPENCV_VERSION=4.14.0
# OpenCV 的 CPU 基线优化开关（opt-in，留空 = OpenCV 默认行为）。
# 仅 armv7 有意义：ARM32 上 NEON 是可选扩展，OpenCV 默认不启用（Baseline 为空）。
# 例：--build-arg OPENCV_CPU_BASELINE=NEON
# 注意：开了 NEON 的 arm/v7 镜像无法在 armv6-only 的 CPU 上运行，故不作默认。
ARG OPENCV_CPU_BASELINE=""

# Install packages
RUN <<EOT
#!/usr/bin/env sh
set -eux
# v3.24 起 py3-onnxruntime / py3-pillow / py3-numpy 均在 community 仓，无需 testing 源
APK_CMD="apk"
if [ "x" != "x${APK_MIRROR}" ]; then
    APK_CMD="apk --repositories-file=/dev/null -X $APK_MIRROR/alpine/v3.24/main -X $APK_MIRROR/alpine/v3.24/community"
fi
$APK_CMD update
# 运行时保留 bash（兼容上层镜像与用户脚本）；file 及其 magic.mgc 特征库用不到（busybox sh 即可）；git 归入 .build_deps 用完即删
$APK_CMD add --update --no-cache bash tzdata ca-certificates python3 py3-six
# ln -s /usr/bin/python3 /usr/bin/python

# 安装 ddddocr 本体并清理（各 OCR 平台共用）：init+fetch 拉取支持 分支名/tag/SHA，--no-deps 安装
install_ddddocr() {
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
    # onnxruntime 的 py3-sympy 依赖仅用于符号形状推断，ddddocr 不使用；连同 dist-info 元数据与 isympy.py 一并删除
    rm -rf /usr/lib/python3.*/site-packages/sympy* /usr/lib/python3.*/site-packages/mpmath* /usr/lib/python3.*/site-packages/isympy.py
    # 删除 numpy 测试套件与标准库 turtledemo（运行时无用）
    rm -rf /usr/lib/python3.*/site-packages/numpy/tests /usr/lib/python3.*/turtledemo
    cd / && rm -rf /ddddocr
}

case "${TARGETPLATFORM}" in
    linux/amd64|linux/arm64|linux/arm/v7|linux/ppc64le|linux/riscv64)
        # 这些架构无 apk py3-opencv（Alpine 因 Qt6 迁移已将其从主流架构移除），PyPI 亦无 musllinux wheel，
        # 故自源码编译最小化 OpenCV：仅 core/imgproc/imgcodecs（ddddocr 实际使用范围），
        # 关闭 Qt/OpenGL/FFmpeg 等 GUI 与视频后端，编译后剥离调试符号
        # 注：ppc64le/riscv64 在 QEMU 下编译耗时显著增加（CI 中约 30-90 分钟），但镜像保持 ~465MB 精简体积；
        # 这两个架构虽有 apk 预编译 opencv，但其 Qt6/X11 依赖链使镜像胀至 ~600-770MB，故不采用
        $APK_CMD add --update --no-cache py3-pillow py3-onnxruntime py3-numpy libprotobuf-lite
        # ddddocr 1.6.1 起为纯 Python 包（pyproject.toml + setuptools 后端），--no-deps 后仅需 pip/setuptools/wheel
        # opencv 编译需要 cmake/编译器/python 头文件/numpy 头文件及图像编解码开发库；git 仅构建期克隆源码用
        $APK_CMD add --update --no-cache --virtual .build_deps py3-pip py3-setuptools py3-wheel \
            git cmake build-base linux-headers python3-dev py3-numpy-dev \
            libjpeg-turbo-dev libpng-dev zlib-dev libwebp-dev
        wget -q -O /tmp/opencv.tar.gz "https://github.com/opencv/opencv/archive/refs/tags/$OPENCV_VERSION.tar.gz"
        tar -C /tmp -xzf /tmp/opencv.tar.gz
        # OpenCV 的目标架构必须显式指定，不能让 cmake 从 uname 推断。
        # 在 GitHub 原生 arm64 runner 上，armv7 容器由内核 compat 模式直接执行（不经 QEMU），
        # uname -m 返回 aarch64 -> cmake 打印 "Detected processor: aarch64" -> 走进 AARCH64
        # 分支：用 aarch64 的检查文件喂 arm32 编译器（NEON 测试 Failed），并按 AArch64 配置
        # NEON_DOTPROD/NEON_BF16 等无效 dispatch。构建能过、冒烟也过，配置却是错的。
        # 所以下面显式指定处理器，并在 configure 后用断言盯住探测结果。
        # armv7 的架构探测修正。四种方案实测对比（都记录在这里，避免以后重复踩）：
        #  1) -DCMAKE_SYSTEM_PROCESSOR=arm          -> 被 cmake 在 project() 里用 uname 覆盖，无效
        #  2) + -DCMAKE_SYSTEM_NAME=Linux（交叉模式）-> 探测正确，但跳过 OpenCV 的 python3 绑定，
        #     最终镜像 import cv2 直接 ModuleNotFoundError
        #  3) setarch linux32                       -> arm64 内核不支持 PER_LINUX32（EINVAL），
        #     这条路只有 x86_64 上的 setarch i386 可行（内核实现了 uname 覆盖）
        #  4) 给 cmake 指定一个"说真话的 uname"      -> 有效，且保持原生编译路径
        # 采用 4)，并用 -DCMAKE_UNAME 显式指定，仅影响这一次 configure，
        # 不像改 PATH 那样波及后续的 apk/pip/python 断言。
        cmake_baseline=""
        if [ -n "${OPENCV_CPU_BASELINE}" ]; then
            cmake_baseline="-DCPU_BASELINE=${OPENCV_CPU_BASELINE}"
        fi
        cmake_uname=""
        if [ "$TARGETARCH" = "arm" ]; then
            mkdir -p /tmp/uname-shim
            printf '#!/bin/sh\n[ "$1" = "-m" ] && { echo armv7l; exit 0; }\nexec /bin/busybox uname "$@"\n' > /tmp/uname-shim/uname
            chmod +x /tmp/uname-shim/uname
            cmake_uname="-DCMAKE_UNAME=/tmp/uname-shim/uname"
        fi
        case "${TARGETARCH}" in
            amd64)   cmake_proc=x86_64 ;;
            arm64)   cmake_proc=aarch64 ;;
            arm)     cmake_proc=arm ;;   # armv7 走 ARM32 分支（配合上面的 uname shim）
            386)     cmake_proc=i386 ;;
            ppc64le) cmake_proc=ppc64le ;;
            riscv64) cmake_proc=riscv64 ;;
            loong64) cmake_proc=loongarch64 ;;
            *) echo "未知 TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;;
        esac
        cmake -S "/tmp/opencv-$OPENCV_VERSION" -B /tmp/opencv-build \
            -DCMAKE_BUILD_TYPE=Release \
            -DCMAKE_INSTALL_PREFIX=/usr \
            -DCMAKE_SYSTEM_PROCESSOR="${cmake_proc}" ${cmake_uname} ${cmake_baseline} \
            -DBUILD_LIST=core,imgproc,imgcodecs,python3 \
            -DBUILD_SHARED_LIBS=ON \
            -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_opencv_apps=OFF \
            -DWITH_QT=OFF -DWITH_GTK=OFF -DWITH_OPENGL=OFF -DWITH_FFMPEG=OFF \
            -DWITH_IPP=OFF -DWITH_TBB=OFF -DWITH_OPENCL=OFF -DWITH_CUDA=OFF -DWITH_V4L=OFF \
            -DBUILD_opencv_python3=ON > /tmp/cmake.log 2>&1 || \
            { echo "ERROR: cmake configure 失败"; tail -80 /tmp/cmake.log; exit 1; }
        grep -E "Detected processor|CPU/HW features|Baseline" /tmp/cmake.log
        # 断言一：cmake 实际采用的处理器必须等于预期（armv7 下应匹配到 armv7l）
        grep -q "Detected processor: ${cmake_proc}" /tmp/cmake.log || \
            { echo "ERROR: cmake 探测到的主机架构与目标 ${cmake_proc} 不一致"; grep "Detected processor" /tmp/cmake.log; exit 1; }
        # 断言二：走对 ARM32 分支后，不应再出现 AArch64 专属的 dispatch 探测
        # （NEON_DOTPROD/NEON_BF16 只在 AARCH64 分支里被定义）。注意 ARM32 的
        # "Baseline:" 默认就是空的——NEON 在 armv7 属于可选项，OpenCV 只有显式
        # -DENABLE_NEON=ON 才加 -mfpu=neon；Alpine 的 armhf 用户态以 armv6 为基线，
        # 强制 NEON 会让 armv6-only 的板子跑不了 armv7 镜像，故不启用。
        if [ "$TARGETARCH" = "arm" ]; then
            ! grep -qE "NEON_DOTPROD|NEON_BF16" /tmp/cmake.log || \
                { echo "ERROR: armv7 构建仍带 AArch64 专属 dispatch，架构判定有误"; exit 1; }
        fi
        cmake --build /tmp/opencv-build -j"$(nproc)"
        cmake --install /tmp/opencv-build
        # 删除 ddddocr 用不到的 OpenCV 数据与头文件：haarcascades/lbpcascades 级联 XML 约 9.6MB、头文件约 4.5MB
        # 注意：只能删 /usr/include/opencv4，不能整个 rm -rf /usr/include——Alpine 3.24 起 pyconfig.h 由
        # python3 包拥有（属运行时文件，不在 .build_deps 内），删了整个目录会让下游镜像
        # （如 pycurl-docker）编译任何 C 扩展时都报 missing Python.h，被迫 apk fix python3 兜底
        rm -rf /usr/share/opencv4 /usr/include/opencv4
        find /usr/lib -name 'libopencv_*.so*' -exec strip --strip-unneeded {} + 2>/dev/null || true
        find /usr/lib/python3.*/site-packages/cv2 -name '*.so' -exec strip --strip-unneeded {} + 2>/dev/null || true
        # 清掉构建期辅助物：uname shim（仅 armv7 用）与 configure 日志不该留在最终镜像里
        rm -rf /tmp/uname-shim /tmp/cmake.log
        rm -rf /tmp/opencv-build "/tmp/opencv-$OPENCV_VERSION" /tmp/opencv.tar.gz
        install_ddddocr
        # .build_deps 内含 git/cmake/编译器/头文件等构建期工具，构建结束全部卸载（file/magic.mgc 未安装，bash 保留）
        $APK_CMD del .build_deps
        # 构建期只断言「产物自洽」，不做行为验证：
        #   - import 通过 = ddddocr 包确实装上了、onnxruntime/cv2 的依赖链没被
        #     前面的瘦身步骤（清 sympy/mpmath、apk del .build_deps）弄断
        #   - pyconfig.h 存活 = 下游镜像能编译 C 扩展
        # 真实推理属于测试，不在构建期跑：那会把测试塞进构建、混淆「构建失败」与
        # 「运行时失败」两种信号，也让产物无法在已知运行时损坏时单独构建出来调试。
        # 推理验证由 CI 的 per-arch 冒烟矩阵执行（tests/smoke.py ocr，覆盖全部
        # 6 个 OCR 平台），本步骤保持微秒级
        python3 -c "import ddddocr, onnxruntime, cv2"
        # 防御性断言：pyconfig.h 必须存活（3.24 起归 python3 包；它是下游镜像编译 C 扩展的前提，
        # 曾在 2290fdc 清理步骤中被 rm -rf /usr/include 误删，导致 pycurl-docker 需要 apk fix python3 兜底）
        ls /usr/include/python3.*/pyconfig.h
        ;;
    *)
        # 386/armv6/s390x 缺 py3-onnxruntime，暂无法支持完整 OCR 栈
        # loong64（龙芯）依赖齐全，但 Docker Hub 官方 alpine 镜像无此变体；
        # CI 中 loong64 由 Dockerfile.loong64（ghcr.io/loong64/alpine 社区基础镜像）单独构建，不会走到本分支
        $APK_CMD add --update --no-cache libprotobuf-lite
        echo "OCR stack (py3-pillow/py3-onnxruntime/opencv) does not currently support ${TARGETPLATFORM}."
        ;;
esac
rm -rf /var/cache/apk/*
rm -rf /usr/share/man/*
EOT
