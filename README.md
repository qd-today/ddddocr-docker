# **ddddocr-Docker**

## **Repository**

**Github :** [https://github.com/qd-today/ddddocr-docker](https://github.com/qd-today/ddddocr-docker)

**DockerHub :** [https://hub.docker.com/r/a76yyyy/ddddocr](https://hub.docker.com/r/a76yyyy/ddddocr)

```bash
docker pull a76yyyy/ddddocr:latest
```

## **这是什么**

基于 Alpine 的 ddddocr 运行环境：ddddocr（通用验证码识别）连同它依赖的 OpenCV、
onnxruntime 一起预编译好，镜像内 `import ddddocr` 即可用——目标机器不需要编译工具链，
也不需要自己处理 musl 下的依赖。

- 支持验证码分类（`classification`）与目标检测（`detection`）两种用法
- 可直接 `docker run` 跑脚本，也可作为基座镜像被上层复用（`FROM a76yyyy/ddddocr:latest`）
- 完整 OCR 能力覆盖 amd64 / arm64 / armv7 / ppc64le / riscv64 / loong64，其余架构见「平台支持矩阵」

## **快速开始**

```bash
# 把本地验证码图片挂进容器，识别结果打印到标准输出
docker run --rm -v "$PWD/captcha.png:/c.png" a76yyyy/ddddocr:latest \
  python3 -c "import ddddocr; print(ddddocr.DdddOcr(show_ad=False).classification(open('/c.png','rb').read()))"
```

```dockerfile
# 作为基座镜像：镜像内已有 ddddocr / cv2 / onnxruntime
FROM a76yyyy/ddddocr:latest
```

## **VERSION**

- ALPINE_VERSION == v3.24
- PYTHON_VERSION == 3.14
- OPENCV_VERSION == 4.14.0（源码编译最小化构建：仅 core/imgproc/imgcodecs + Python 绑定，无 GUI/视频后端）
- DDDDOCR_VERSION == 1.6.1（上游未打版本 tag，发布时以 `ddddocr.version` 文件锁定 commit SHA）

## **版本策略**

- `latest` 标签：跟随上游 master，经 workflow_dispatch（勾选 push）或推送版本 tag 时构建发布（默认分支 main 的普通推送不触发构建，仅同步 Docker Hub 描述）
- 版本号标签（如 `1.6.1`）：与 ddddocr 上游版本对齐，构建时使用 `ddddocr.version` 中锁定的 commit，可复现
- 发布新版本流程：更新 `ddddocr.version` 为上游目标 commit → 打对应版本 tag → CI 自动构建并推送

## **平台支持矩阵**

| 平台 | 能力 | OpenCV 来源 | 镜像体积* | 说明 |
|---|---|---|---|---|
| linux/amd64 | ✅ 完整 OCR | 源码编译 4.14.0（最小化） | ~465MB | 主平台 |
| linux/arm64 | ✅ 完整 OCR | 源码编译 4.14.0（最小化） | ~465MB | 主平台 |
| linux/arm/v7 | ✅ 完整 OCR | 源码编译 4.14.0（最小化） | ~465MB | |
| linux/ppc64le | ✅ 完整 OCR | 源码编译 4.14.0（最小化） | ~465MB | QEMU 下编译耗时较长 |
| linux/riscv64 | ✅ 完整 OCR | 源码编译 4.14.0（最小化） | ~465MB | QEMU 下编译耗时较长 |
| linux/loong64 | ✅ 完整 OCR | 源码编译 4.14.0（最小化） | ~465MB | 基础镜像用 `ghcr.io/loong64/alpine:3.24`（龙芯社区构建，因 Docker Hub 官方无 loong64），见下方说明 |
| linux/386、linux/arm/v6、linux/s390x | ❌ **空壳（无任何 OCR 能力）** | 无 | ~50MB | 见下方警告 |

\* 体积为未压缩估算，全部 OCR 平台一致（约 465MB）。

> ### ⚠️ 386 / armv6 / s390x 是「空壳镜像」，不能用于验证码识别
>
> 镜像里**只有 python3 + libprotobuf-lite，没有 OpenCV，也没有 ddddocr 包本身**：
>
> - `import ddddocr` 直接 `ModuleNotFoundError`
> - 任何依赖 OCR 的功能（qd 的验证码识别任务）在这些平台上**必然失败**
> - `docker pull a76yyyy/ddddocr:latest` 在这些架构上会「成功」，但拉到的就是空壳
>
> 三个平台的缺失环节不同：
>
> | 平台 | Alpine 架构名 | `onnxruntime` C 库 | `py3-onnxruntime` | 原因 |
> |---|---|---|---|---|
> | linux/386 | `x86` | ✗ | ✗ | 上游在 x86 上编译失败，APKBUILD 标注 `arch="all !s390x !x86"` |
> | linux/s390x | `s390x` | ✗ | ✗ | 同上 |
> | linux/arm/v6 | `armhf` | ✓ | ✗ | python 绑定被 `py3-flattbuffers` 阻塞（APKBUILD: `armhf) ;; # blocked by py3-flattbuffers`），C 库本身可用 |
>
> 保留这三个平台的唯一原因：让 `latest` 多架构 manifest 覆盖完整，使上层镜像
> （pycurl-docker 等 `FROM a76yyyy/ddddocr:latest`）在这些架构上仍能正常构建
> ——它们本来就只需要 python3 与 libprotobuf-lite。若你需要在这些架构上做 OCR，
> 请改为自建（自行编译 onnxruntime）。

**loong64 特别说明**：Docker Hub 官方 alpine 镜像不提供 loong64 变体，故 loong64 构建使用龙芯社区维护的 [loong64/docker-library](https://github.com/loong64/docker-library)（ghcr.io/loong64/alpine，QEMU on GitHub Actions 构建，源码来自 docker-library）。该基础镜像为第三方依赖，若其停止维护需回退至 `FROM scratch` + minirootfs 方案。loong64 变体通过独立 Dockerfile 构建后合并进主 tag 的多架构 manifest，同时保留 `-loong64` 后缀 tag（如 `latest-loong64`）供直接拉取。

## **构建说明**

- OpenCV 不采用 apk 的 py3-opencv：其 Qt/OpenGL/FFmpeg 依赖链约 236MB，ddddocr 用不到；且 PyPI 无 musllinux wheel，故改为源码编译
- 编译产物经 `strip --strip-unneeded` 剥离符号，各 OCR 平台镜像约 465MB
- 体积优化（约 50MB 死重清理，不影响任何功能）：不安装 file/magic.mgc 特征库、git 归入 .build_deps 用完即卸、删除 OpenCV haarcascades/lbpcascades 级联数据与 `/usr/include/opencv4` 头文件（注意保留 `/usr/include` 其余内容——Alpine 3.24 起 `pyconfig.h` 由 python3 包拥有，是下游镜像编译 C 扩展的前提）、清 sympy/mpmath 元数据残留与 numpy 测试套件
- 本地构建加速：`docker build --build-arg APK_MIRROR=https://mirrors.tuna.tsinghua.edu.cn .`

### **CPU 基线优化（`OPENCV_CPU_BASELINE`）**

`--build-arg OPENCV_CPU_BASELINE=NEON` 只作用于本仓库自编的 OpenCV；默认留空，即交由
OpenCV 自行决定（ARM32 上 OpenCV 不设基线，走纯标量路径）。该参数只在 ARM32 上有意义——
其余架构 OpenCV 会自己检测并启用 SSE2/NEON 等基线。

不设默认的原因：

- **收益被推理占比稀释**：ARM32 开 NEON 后预处理单步快 1.4–2.0×（cvtColor 1.85×、
  GaussianBlur 1.40×、threshold 2.00×），但 OpenCV 只占端到端约 11%，其余是 onnxruntime
  推理，端到端差异在噪声范围内
- **兼容性**：Alpine 的 armhf 用户态以 armv6 为基线，开了 NEON 的 `arm/v7` 镜像无法在
  armv6-only 的 CPU 上运行
- **构建成本**：约 4 倍（NEON 基线会把所有向量化分支实例化编译）

**onnxruntime 不需要为 NEON 自编**：其上游 `cmake/onnxruntime_mlas.cmake` 在
`CMAKE_SYSTEM_PROCESSOR` 匹配 `^arm.*` 时无条件追加 `-mfpu=neon`，并编入
`aarch32/QgemmU8X8KernelNeon.S` 等 NEON 内核，与发行版 CFLAGS 无关。因此 Alpine 的
armv7 `py3-onnxruntime` 包本身就是 NEON 版本（`readelf -A` 可见
`Tag_Advanced_SIMD_arch: NEONv1`），自编不会带来额外收益。

基准可用 `tests/bench.py` 复现：`docker run --rm -i --platform linux/arm/v7 <image> python3 - < tests/bench.py`。
须在能原生执行 AArch32 的机器上运行（QEMU 下墙钟由指令翻译主导，数字无意义）；
脚本只输出数字、不做断言。

---

<details>
<summary><b>CI 架构（维护者向）</b>：构建 / 测试 / 发布三阶段解耦</summary>

### **流水线**

```
plan    计算架构分组（按 dispatch 的 platforms 输入裁剪）
  ├─ build x86      (ubuntu-latest)     amd64(原生) + 386
  ├─ build arm      (ubuntu-24.04-arm)  arm64(原生) + armv7 + armv6   ← GitHub 原生 arm64 runner
  ├─ build ppc64le  (ubuntu-latest)     ppc64le + s390x
  ├─ build riscv64  (ubuntu-latest)     riscv64
  └─ build loong64  (ubuntu-latest)     loong64（独立 Dockerfile）
        ↓ 全部构建成功
  smoke（9 个平台各一个 job）  从构建层缓存复用镜像，逐平台实跑（6 OCR 推理 + 3 空壳契约）
        ↓ 全部冒烟通过
  publish  各架构组按 digest 合并成正式 tag → 校验 manifest 平台完整性
```

### **设计原则**

1. **发布即全绿**：`publish` 需要所有构建 + 所有冒烟 job 成功。任何测试失败都不会产生 tag
2. **零重复编译**：构建阶段把层缓存写入 GHA cache（按架构组隔离 scope），冒烟与发布阶段
   `cache-from` 命中同一份缓存，只做导出、不重新编译。同一 commit 的「验证构建 → 冒烟 → 发布」
   三次跑都复用同一份产物
3. **不产临时 tag**：发布模式下各架构组用 `push-by-digest` 推到 ghcr（无 tag），`publish`
   用 `imagetools create` 把各组 digest 合并成正式多架构 tag，因此不会在 tag 列表里留下
   可被拉取的一次性中间产物

### **workflow_dispatch 输入**

| 输入 | 默认 | 说明 |
|---|---|---|
| `push` | false | 不勾选 = 只构建 + 冒烟验证，**不发布任何镜像** |
| `platforms` | 空（= 全部 9 平台） | 平台子集加速迭代，如 `linux/riscv64`。**子集构建默认禁止发布**（防止不完整 manifest 覆盖正式 tag），确需如此请勾 `allow_partial_publish` |
| `native_arm` | true | 用 `ubuntu-24.04-arm` 原生构建 arm64（比 QEMU 快 3-5 倍）；该 runner 不可用时取消勾选回退 QEMU |
| `allow_partial_publish` | false | 逃生阀：允许用平台子集发布 |

### **测试防线（两层，都在构建之外）**

- **per-arch 冒烟矩阵（9 个 job，每平台一个）**：用构建阶段的层缓存重建单平台镜像
  （命中缓存 = 秒级，不重新编译），再在该架构上真跑 `tests/smoke.py`，模式由平台类型显式传入：
  - 6 个 OCR 平台 `-- ocr`：依赖 import → 模型加载 → 图像编码 → ONNX 前向 → 解码输出。
    ppc64le/riscv64/loong64 的 OpenCV/onnxruntime 都是 QEMU 下源码编译，架构相关的
    ABI/数值问题只有真实前向才会暴露
  - 3 个空壳平台 `-- degraded`：断言 python3 可用、libprotobuf-lite 在位，并**确认
    `ddddocr`/`cv2`/`onnxruntime` 确实不存在**（与上面「空壳镜像」一节的契约一一对应）
  - 模式由 CI 显式传入、不做自动探测：自动探测会在 ddddocr 意外缺失时静默降级成空壳检查
    并通过，从而掩盖真实回归
  - 脚本用 stdin 喂进容器（`python3 - <mode>`），不进镜像、不依赖 bind mount、不依赖外部网络
- **发布后 manifest 断言**：每个正式 tag 的平台集合必须与计划完全一致，不一致直接 fail
  （防止正式 tag 被不完整 manifest 覆盖）

> 构建期只保留「产物自洽」的微秒级断言（`import ddddocr, onnxruntime, cv2` 通过 +
> `pyconfig.h` 存活）。**推理不在构建期跑**——那会把测试塞进构建、混淆「构建失败」与
> 「运行时失败」两种信号，也让产物在已知运行时损坏时无法单独构建出来调试。

### **其他**

- loong64 使用独立 Dockerfile（`Dockerfile.loong64`，仅基础镜像不同）构建并合并进主 tag 的多架构 manifest；CI 含 Dockerfile 同步校验，防止两个文件演化漂移
- 勾选 `push` 或推送版本 tag（如 `1.6.1`）时才真正发布到 ghcr.io 与 Docker Hub；tag 发布始终为全平台构建
- tag 发布使用 `ddddocr.version` 锁定的上游 commit（可复现）；dispatch 默认跟随上游 master
- 默认分支 main 的普通推送不触发构建，只同步 Docker Hub 描述

</details>
