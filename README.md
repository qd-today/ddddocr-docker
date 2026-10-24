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

- `latest` 标签：跟随上游 master，经 workflow_dispatch（勾选 push）或推送版本 tag 时构建发布（默认分支 main 的普通推送不触发构建，仅同步 Docker Hub 描述）
- 版本号标签（如 `1.6.1`）：与 ddddocr 上游版本对齐，构建时使用 `ddddocr.version` 中锁定的 commit，可复现
- 发布新版本流程：更新 `ddddocr.version` 为上游目标 commit → 打对应版本 tag → CI 自动构建并推送

## **Tips**

> Onnxruntime Builder does not currently support building i386 and s390x wheels!

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
> 这三个平台的上游依赖链缺失（`onnxruntime` 不提供 i386 / s390x wheel，armv6 无可用
> onnxruntime 构建），镜像里**只有 python3 + libprotobuf-lite，没有 OpenCV，也没有
> ddddocr 包本身**：
>
> - `import ddddocr` 直接 `ModuleNotFoundError`
> - 任何依赖 OCR 的功能（qd 的验证码识别任务）在这些平台上**必然失败**
> - `docker pull a76yyyy/ddddocr:latest` 在这些架构上会「成功」，但拉到的就是空壳
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

## **CI 架构：构建 / 测试 / 发布三阶段解耦**

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

**三条设计原则**：

1. **发布即全绿**：`publish` 需要所有构建 + 所有冒烟 job 成功。任何测试失败都不会产生 tag
   （旧流程是「构建成功就发布」，运行时状态零验证）
2. **零重复编译**：构建阶段把层缓存写入 GHA cache（按架构组隔离 scope），冒烟与发布阶段
   `cache-from` 命中同一份缓存，只做导出、不重新编译。同一 commit 的「验证构建 → 冒烟 → 发布」
   三次跑都复用同一份产物
3. **不产临时 tag**：发布模式下各架构组用 `push-by-digest` 推到 ghcr（无 tag），`publish`
   用 `imagetools create` 把各组 digest 合并成正式多架构 tag。因此不会在 Hub 上留下
   `staging-*` 之类的一次性 tag

**workflow_dispatch 输入**：

| 输入 | 默认 | 说明 |
|---|---|---|
| `push` | false | 不勾选 = 只构建 + 冒烟验证，**不发布任何镜像** |
| `platforms` | 空（= 全部 9 平台） | 平台子集加速迭代，如 `linux/riscv64`。**子集构建默认禁止发布**（防止不完整 manifest 覆盖正式 tag），确需如此请勾 `allow_partial_publish` |
| `native_arm` | true | 用 `ubuntu-24.04-arm` 原生构建 arm64（比 QEMU 快 3-5 倍）；该 runner 不可用时取消勾选回退 QEMU |
| `allow_partial_publish` | false | 逃生阀：允许用平台子集发布 |

**测试防线（两层，都在构建之外）**：

- **per-arch 冒烟矩阵（9 个 job，每平台一个）**：用构建阶段的层缓存重建单平台镜像
  （命中缓存 = 秒级，不重新编译），再在该架构上真跑：
  - 6 个 OCR 平台执行 `tests/ocr-selfcheck.py`：依赖 import → 模型加载 → 图像编码 →
    ONNX 前向 → 解码输出。ppc64le/riscv64/loong64 的 OpenCV/onnxruntime 都是 QEMU 下
    源码编译，架构相关的 ABI/数值问题只有真实前向才会暴露
  - 3 个空壳平台执行 `tests/smoke-degraded.sh`：断言 python3 可用、libprotobuf-lite 在位，
    并**确认 `ddddocr`/`cv2` 确实不存在**（与下面「空壳镜像」一节的契约一一对应）
  - 脚本用 stdin 喂进容器（`python3 -` / `sh -s`），不进镜像、不依赖 bind mount
- **发布后 manifest 断言**：每个正式 tag 的平台集合必须与计划完全一致，不一致直接 fail
  （1.6.1 那次 `latest` 被单架构覆盖的事故，从此由 CI 自动拦截）

> 构建期只保留「产物自洽」的微秒级断言（`import ddddocr, onnxruntime, cv2` 通过 +
> `pyconfig.h` 存活）。**推理不在构建期跑**——那会把测试塞进构建、混淆「构建失败」与
> 「运行时失败」两种信号，也让产物在已知运行时损坏时无法单独构建出来调试。

**其他**：

- loong64 使用独立 Dockerfile（`Dockerfile.loong64`，仅基础镜像不同）构建并合并进主 tag 的多架构 manifest；CI 含 Dockerfile 同步校验，防止两个文件演化漂移
- 勾选 `push` 或推送版本 tag（如 `1.6.1`）时才真正发布到 ghcr.io 与 Docker Hub；tag 发布始终为全平台构建
- tag 发布使用 `ddddocr.version` 锁定的上游 commit（可复现）；dispatch 默认跟随上游 master
- 默认分支 main 的普通推送不触发构建，只同步 Docker Hub 描述
