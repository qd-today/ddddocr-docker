# **ddddocr-Docker**

## **Repository**

**Github :** [https://github.com/qd-today/ddddocr-docker](https://github.com/qd-today/ddddocr-docker)

**DockerHub :** [https://hub.docker.com/r/a76yyyy/ddddocr](https://hub.docker.com/r/a76yyyy/ddddocr)

```bash
docker pull a76yyyy/ddddocr:latest
```

## **VERSION**

- ALPINE_VERSION == v3.24
- PYTHON_VERSION == 3.14
- OPENCV_VERSION == 4.14.0（源码编译最小化构建：仅 core/imgproc/imgcodecs + Python 绑定，无 GUI/视频后端）
- DDDDOCR_VERSION == 1.6.1（上游未打版本 tag，发布时以 `ddddocr.version` 文件锁定 commit SHA）

## **版本策略**

- `latest` 标签：跟随上游 master，经 workflow_dispatch（勾选 push）或默认分支推送时构建发布
- 版本号标签（如 `1.6.1`）：与 ddddocr 上游版本对齐，构建时使用 `ddddocr.version` 中锁定的 commit，可复现
- 发布新版本流程：更新 `ddddocr.version` 为上游目标 commit → 打对应版本 tag → CI 自动构建并推送

## **Tips**

> Onnxruntime Builder does not currently support building i386 and s390x wheels!

## **平台支持矩阵**

| 平台 | OCR 栈 | OpenCV 来源 | 镜像体积* | 说明 |
|---|---|---|---|---|
| linux/amd64 | ✓ 完整 | 源码编译 4.14.0（最小化） | ~465MB | 主平台 |
| linux/arm64 | ✓ 完整 | 源码编译 4.14.0（最小化） | ~465MB | 主平台 |
| linux/arm/v7 | ✓ 完整 | 源码编译 4.14.0（最小化） | ~465MB | |
| linux/ppc64le | ✓ 完整 | 源码编译 4.14.0（最小化） | ~465MB | QEMU 下编译耗时较长 |
| linux/riscv64 | ✓ 完整 | 源码编译 4.14.0（最小化） | ~465MB | QEMU 下编译耗时较长 |
| linux/loong64 | ✓ 完整 | 源码编译 4.14.0（最小化） | ~465MB | 基础镜像用 `ghcr.io/loong64/alpine:3.24`（龙芯社区构建，因 Docker Hub 官方无 loong64），见下方说明 |
| linux/386、linux/arm/v6、linux/s390x | ✗ 降级 | 无 | ~50MB | 缺 py3-onnxruntime，镜像仅含 python3 + libprotobuf-lite |

\* 体积为未压缩估算，全部 OCR 平台一致（约 465MB）。

**loong64 特别说明**：Docker Hub 官方 alpine 镜像不提供 loong64 变体，故 loong64 构建使用龙芯社区维护的 [loong64/docker-library](https://github.com/loong64/docker-library)（ghcr.io/loong64/alpine，QEMU on GitHub Actions 构建，源码来自 docker-library）。该基础镜像为第三方依赖，若其停止维护需回退至 `FROM scratch` + minirootfs 方案。loong64 变体通过独立 Dockerfile 构建后合并进主 tag 的多架构 manifest，同时保留 `-loong64` 后缀 tag（如 `latest-loong64`）供直接拉取。

## **构建说明**

- OpenCV 不采用 apk 的 py3-opencv：其 Qt/OpenGL/FFmpeg 依赖链约 236MB，ddddocr 用不到；且 PyPI 无 musllinux wheel，故改为源码编译
- 编译产物经 `strip --strip-unneeded` 剥离符号，各 OCR 平台镜像约 465MB
- 体积优化（约 50MB 死重清理，不影响任何功能）：不安装 file/magic.mgc 特征库、git 归入 .build_deps 用完即卸、删除 OpenCV haarcascades/lbpcascades 级联数据与 `/usr/include` 头文件、清 sympy/mpmath 元数据残留与 numpy 测试套件
- 本地构建加速：`docker build --build-arg APK_MIRROR=https://mirrors.tuna.tsinghua.edu.cn .`

## **CI 构建验证（无 push 模式）**

- workflow_dispatch 提供两个输入：
  - `push`（默认 **false**）：仅执行完整构建验证，**不推送任何镜像**，用于发布前验证
  - `platforms`（默认空 = 全部 9 平台，含 loong64）：可指定平台子集加速迭代，如 `linux/riscv64,linux/arm64`（逗号分隔、不要空格）。⚠️ 子集构建若同时勾选 push，会以不完整 manifest 覆盖对应 tag，仅供验证时使用
- loong64 使用独立 Dockerfile（`Dockerfile.loong64`，仅基础镜像不同）构建并合并进主 tag 的多架构 manifest；CI 含 Dockerfile 同步校验，防止两个文件演化漂移
- 勾选 `push` 或推送版本 tag（如 `1.6.1`）时才真正发布到 ghcr.io 与 Docker Hub，且 tag 发布始终为全平台构建
- tag 发布使用 `ddddocr.version` 锁定的上游 commit；dispatch 默认跟随上游 master
