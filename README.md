# ddddocr Docker 镜像（Alpine）

基于 Alpine 的 [ddddocr](https://github.com/sml2h3/ddddocr) 运行环境：ddddocr 与它依赖的
OpenCV、onnxruntime 一并预编译，容器内 `import ddddocr` 即可使用，不需要在目标机器上准备
编译工具链，也不需要自行处理 musl 下的依赖。

- Docker Hub：<https://hub.docker.com/r/a76yyyy/ddddocr>
- 源码：[qd-today/ddddocr-docker](https://github.com/qd-today/ddddocr-docker)

## 快速开始

```bash
docker pull a76yyyy/ddddocr:latest
```

识别一张本地图片，结果打印到标准输出：

```bash
docker run --rm -v "$PWD/captcha.png:/c.png" a76yyyy/ddddocr:latest \
  python3 -c "import ddddocr; print(ddddocr.DdddOcr(show_ad=False).classification(open('/c.png','rb').read()))"
```

作为基础镜像使用：

```dockerfile
FROM a76yyyy/ddddocr:latest
```

镜像内已有 ddddocr、cv2 与 onnxruntime，直接 import 即可：

```python
import ddddocr

ocr = ddddocr.DdddOcr(show_ad=False)
text = ocr.classification(image_bytes)        # 验证码分类

det = ddddocr.DdddOcr(det=True, show_ad=False)
boxes = det.detection(image_bytes)            # 目标检测
```

## 镜像内容

| 组件 | 版本 | 说明 |
|---|---|---|
| Alpine | 3.24 | 基础镜像 |
| Python | 3.14 | |
| ddddocr | 1.6.1 | 上游未打版本 tag，版本由仓库内 `ddddocr.version` 锁定的 commit SHA 决定 |
| OpenCV | 4.14.0 | 源码编译，仅 core / imgproc / imgcodecs 与 Python 绑定，无 GUI 与视频后端 |
| onnxruntime | Alpine 包 1.24.4 | 平台可用性见下节 |

## 支持的平台

| 平台 | OCR 能力 | 镜像体积 |
|---|---|---|
| linux/amd64 | ✓ | ~465 MB |
| linux/arm64 | ✓ | ~465 MB |
| linux/arm/v7 | ✓ | ~465 MB |
| linux/ppc64le | ✓ | ~465 MB |
| linux/riscv64 | ✓ | ~465 MB |
| linux/loong64 | ✓ | ~465 MB |
| linux/386、linux/arm/v6、linux/s390x | ✗ | ~50 MB |

体积为未压缩值，所有具备 OCR 能力的平台一致。

### 不提供 OCR 的三个平台

`linux/386`、`linux/arm/v6`、`linux/s390x` 的镜像里只有 python3 与 libprotobuf-lite，
既没有 OpenCV，也没有 ddddocr 包本身——`import ddddocr` 会直接抛 `ModuleNotFoundError`。
`docker pull` 在这些架构上会成功，但拉到的镜像无法做验证码识别。

保留它们是为了让 `latest` 的多架构 manifest 覆盖完整，使以本镜像为基础的项目
（如 pycurl-docker 的 `FROM a76yyyy/ddddocr:latest`）在这些架构上仍能构建——那些场景
只需要 python3 与 libprotobuf-lite。要在这些架构上识别验证码，需自行编译 onnxruntime
的 Python 绑定。

三个平台缺失的环节并不相同：

| 平台 | Alpine 架构名 | onnxruntime 库 | Python 绑定 | 原因 |
|---|---|---|---|---|
| linux/386 | `x86` | ✗ | ✗ | 上游在 x86 上编译失败，APKBUILD 标注 `arch="all !s390x !x86"` |
| linux/s390x | `s390x` | ✗ | ✗ | 同上 |
| linux/arm/v6 | `armhf` | ✓ | ✗ | `flatbuffers` 在 armhf 被整体排除（`arch="all !armhf"`，注释「armhf: blocked by bus error in tests」），`py3-flatbuffers` 因此缺失，onnxruntime 的 Python 子包被禁用；C 库本身可用 |

### loong64 的基础镜像

Docker Hub 的官方 alpine 镜像没有 loong64 变体，因此 loong64 使用龙芯社区维护的
[loong64/docker-library](https://github.com/loong64/docker-library)（`ghcr.io/loong64/alpine`，
源码来自 docker-library）。这是第三方依赖，若其停止维护，需回退到 `FROM scratch` 加
minirootfs 的方案。loong64 由独立 Dockerfile 构建后合并进主 tag 的 manifest，同时保留
`latest-loong64` 这类后缀 tag 可直接拉取。

## 标签

| 标签 | 含义 |
|---|---|
| `latest` | 跟随上游 master，每次发布重新构建 |
| `1.6.1` 等版本号 | 与 ddddocr 上游版本对齐，使用 `ddddocr.version` 锁定的 commit，可复现 |
| `latest-loong64` 等 | loong64 单架构 tag |

发布新版本：把 `ddddocr.version` 更新为目标 commit，推对应版本号 tag，CI 构建并推送。
默认分支的普通推送不触发构建，仅同步 Docker Hub 上的说明；`latest` 的日常更新走
workflow_dispatch（勾选 push）。

## 构建

- **OpenCV 源码编译**：apk 的 `py3-opencv` 会带入 Qt / OpenGL / FFmpeg 依赖链（约 236 MB），
  ddddocr 用不到；PyPI 也没有 musllinux wheel，因此改为自编最小化版本。
- **镜像精简**（约 50 MB，不影响功能）：不安装 file 的 magic.mgc 特征库；git 归入构建期
  临时依赖，用完即卸；删除 OpenCV 的 haarcascades / lbpcascades 与 `/usr/include/opencv4`
  头文件（`/usr/include` 的其余内容必须保留——Alpine 3.24 起 `pyconfig.h` 由 python3 包提供，
  是上层镜像编译 C 扩展的前提）；清理 sympy / mpmath 元数据残留与 numpy 测试套件。
- **剥离符号**：构建产物经 `strip --strip-unneeded` 处理。
- **本地构建加速**：`docker build --build-arg APK_MIRROR=https://mirrors.tuna.tsinghua.edu.cn .`

### ARMv7 的 CPU 基线（`OPENCV_CPU_BASELINE`）

`--build-arg OPENCV_CPU_BASELINE=NEON` 让自编的 OpenCV 以 NEON 为基线；默认留空，即 ARM32
上不设基线、走标量路径。该参数只影响 OpenCV，也只对 ARM32 有意义——其余架构由 OpenCV
自行检测并启用 SSE2 / NEON 等基线。

默认关闭的原因：

- **收益落不到端到端**。ARM32 开 NEON 后预处理单步快 1.4–2.0×（cvtColor 1.85×、
  GaussianBlur 1.40×、threshold 2.00×，合计 3.59 → 2.54 ms），但验证码图片在 120×40 量级，
  `imdecode + resize + gray` 合计不到 1 ms；识别时间几乎都在 onnxruntime 推理上。
- **兼容性**。以 NEON 为基线后，`import cv2` 及任何 OpenCV 调用在无 NEON 的 ARMv7
  （如 Marvell Armada 370/XP、部分 Cortex-A5）上会触发 SIGILL。本镜像同时被用作不含 OCR
  的 Python 基座，那类用法不需要 NEON。
- **构建耗时约为 4 倍**——NEON 基线会把所有向量化分支实例化编译。

onnxruntime 无需为 NEON 自编：上游 `cmake/onnxruntime_mlas.cmake` 对
`CMAKE_SYSTEM_PROCESSOR` 匹配 `^arm.*` 的情况无条件追加 `-mfpu=neon` 并编译 NEON 内核，
与发行版的编译参数无关，因此 Alpine 的 armv7 `py3-onnxruntime` 本身就是 NEON 版本
（`readelf -A` 可见 `Tag_Advanced_SIMD_arch: NEONv1`）。这也意味着**仅用于 OCR 时，armv7
本来就要求 CPU 支持 NEON**：MLAS 只在 ARM64 上做运行时特性检测，ARM32 没有回退路径。

基准可用 `tests/bench.py` 复现：

```bash
docker run --rm -i --platform linux/arm/v7 <image> python3 - < tests/bench.py
```

该脚本需在能原生执行 AArch32 的机器上运行——QEMU 下墙钟由指令翻译主导，数字没有参考价值。

---

<details>
<summary>CI 架构（维护者）</summary>

### 流水线

```
plan    计算架构分组（按 dispatch 的 platforms 输入裁剪）
  ├─ build x86      (ubuntu-latest)     amd64(原生) + 386
  ├─ build arm      (ubuntu-24.04-arm)  arm64(原生) + armv7 + armv6   ← GitHub 原生 arm64 runner
  ├─ build ppc64le  (ubuntu-latest)     ppc64le + s390x
  ├─ build riscv64  (ubuntu-latest)     riscv64
  └─ build loong64  (ubuntu-latest)     loong64（独立 Dockerfile）
        ↓ 全部构建成功
  smoke（9 个平台各一个 job）  复用构建层缓存重建镜像后逐平台实跑（6 个 OCR + 3 个降级检查）
        ↓ 全部冒烟通过
  publish  各架构组按 digest 合并成正式 tag → 校验 manifest 平台完整性
```

### 设计原则

1. **发布即全绿**：`publish` 需要所有构建与所有冒烟 job 成功，任何测试失败都不会产生 tag。
2. **零重复编译**：构建阶段把层缓存写入 GHA cache（按架构组隔离 scope），冒烟与发布阶段
   `cache-from` 命中同一份缓存，只做导出。同一 commit 的「验证构建 → 冒烟 → 发布」复用同一份产物。
3. **不产临时 tag**：发布模式下各架构组用 `push-by-digest` 推到 ghcr（不带 tag），`publish`
   用 `imagetools create` 合并成正式多架构 tag，tag 列表里不会留下可被拉取的一次性中间产物。

### workflow_dispatch 输入

| 输入 | 默认 | 说明 |
|---|---|---|
| `push` | false | 不勾选即只构建与冒烟验证，不发布任何镜像 |
| `platforms` | 空（全部 9 平台） | 平台子集，用于加速迭代，如 `linux/riscv64`。子集构建默认禁止发布，确需如此请勾 `allow_partial_publish` |
| `native_arm` | true | 用 `ubuntu-24.04-arm` 原生构建 arm64（比 QEMU 快 3–5 倍）；该 runner 不可用时取消勾选回退 QEMU |
| `allow_partial_publish` | false | 允许用平台子集发布 |

### 测试防线

两层，都在构建之外。

- **per-arch 冒烟矩阵**：9 个平台各一个 job，用构建阶段的层缓存重建单平台镜像（命中缓存
  为秒级），再在该架构上真正运行 `tests/smoke.py`，模式由 CI 显式传入：
  - 6 个具备 OCR 的平台传 `ocr`：依赖 import → 模型加载 → 图像编码 → ONNX 前向 → 解码输出。
    ppc64le / riscv64 / loong64 的 OpenCV 与 onnxruntime 都在 QEMU 下源码编译，架构相关的
    ABI 与数值问题只有真实前向才会暴露。
  - 3 个无 OCR 的平台传 `degraded`：断言 python3 可用、libprotobuf-lite 在位，并确认
    `ddddocr` / `cv2` / `onnxruntime` 确实不存在，与「不提供 OCR 的三个平台」一节一致。
  - 模式由 CI 显式传入而不做自动探测：自动探测会在 ddddocr 意外缺失时静默降级成降级检查
    并通过，掩盖真实回归。
  - 脚本经 stdin 喂进容器（`python3 - <mode>`），不进镜像、不依赖 bind mount 与外部网络。
- **发布后 manifest 断言**：每个正式 tag 的平台集合必须与计划完全一致，否则失败，防止正式
  tag 被不完整 manifest 覆盖。

构建期只保留产物自洽的微秒级断言（`import ddddocr, onnxruntime, cv2` 通过、
`pyconfig.h` 存活）。推理不在构建期执行——那会把测试塞进构建，混淆「构建失败」与
「运行时失败」两种信号，也让产物在已知运行时损坏时无法单独构建出来排查。

### 其他

- loong64 使用独立 Dockerfile（`Dockerfile.loong64`，仅基础镜像不同），CI 含两个文件的
  同步校验，防止演化漂移。
- 勾选 `push` 或推送版本 tag 时才真正发布到 ghcr.io 与 Docker Hub；tag 发布始终为全平台构建。
- tag 发布使用 `ddddocr.version` 锁定的 commit，可复现；dispatch 默认跟随上游 master。
- 默认分支的普通推送不触发构建，只同步 Docker Hub 说明。

</details>
