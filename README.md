# ddddocr Docker 镜像（Alpine）

ddddocr 运行栈的 musllinux wheel 分发，另附装好的可运行镜像。三个包都在本仓库自编或
自打包：`ddddocr`（纯 python + 模型文件）、`opencv`（最小化）、`Pillow`；onnxruntime 与
numpy 取自 [onnxruntime-docker](https://github.com/qd-today/onnxruntime-docker) 的 wheelhouse。

- Docker Hub：<https://hub.docker.com/r/a76yyyy/ddddocr>
- 源码：[qd-today/ddddocr-docker](https://github.com/qd-today/ddddocr-docker)

## 标签

| 标签 | 内容 |
|---|---|
| `1.6.1-wheelhouse` | `scratch` + `/wheels`：三个 wheel、`SHA256SUMS`、`system-packages.txt`、PEP 503 索引 |
| `1.6.1` | `alpine:3.24` + Python 3.14 + 上述包（含 onnxruntime / numpy） |
| `wheelhouse` / `latest` | 上面两者的滚动标签 |

## 快速开始

直接用镜像：

```bash
docker run --rm -v "$PWD/captcha.png:/c.png" a76yyyy/ddddocr:latest \
  python3 -c "import ddddocr; print(ddddocr.DdddOcr(show_ad=False).classification(open('/c.png','rb').read()))"
```

```dockerfile
FROM a76yyyy/ddddocr:latest
```

从 wheelhouse 装到自己的镜像里（需要两个 wheelhouse：本仓库的与 onnxruntime 的）：

```dockerfile
# syntax=docker/dockerfile:1.7
FROM alpine:3.24
RUN --mount=type=bind,from=a76yyyy/ddddocr:1.6.1-wheelhouse,source=/wheels,target=/w1 \
    --mount=type=bind,from=a76yyyy/onnxruntime:1.24.4-wheelhouse,source=/wheels,target=/w2 \
    apk add --no-cache $(cat /w1/system-packages.txt) uv && \
    uv pip install --system --break-system-packages --no-cache --no-deps \
        --no-index --find-links /w1 --find-links /w2 \
        ddddocr opencv Pillow onnxruntime numpy && \
    uv pip install --system --break-system-packages --no-cache \
        flatbuffers packaging protobuf sympy
```

三步各有原因：

| 步骤 | 原因 |
|---|---|
| `apk add $(cat /w1/system-packages.txt)` | wheel 只依赖解释器与 `libz`，清单就是全部前置条件 |
| `--no-index --find-links` + `--no-deps` | uv 把 `file://` 索引排在 PyPI 之后，不加 `--no-index` 会装成 PyPI 的同名包；`--no-deps` 避免解析器去 PyPI 找 opencv |
| 最后一条装 `flatbuffers/packaging/protobuf/sympy` | onnxruntime 的纯 python 依赖，各架构都有轮子，走 PyPI |

`/w1/simple` 是 PEP 503 索引，链接为相对路径，可与 wheel 目录一起挂到任意位置；需要与
PyPI 混装时用 `--extra-index-url file:///w1/simple`，但注意上表的优先级问题。

## 镜像内容

| 组件 | wheelhouse | runtime |
|---|---|---|
| 基础镜像 | `scratch` | `alpine:3.24`；loong64 为 `ghcr.io/loong64/alpine:3.24` |
| Python | — | 3.14 |
| ddddocr | 1.6.1（`py3-none-any`） | 同左 |
| OpenCV | 4.14.0（`musllinux_1_2`） | 同左 |
| Pillow | 13.0.0（`musllinux_1_2`） | 同左 |
| onnxruntime / numpy | — （在 onnxruntime 的 wheelhouse 里） | 1.24.4 / 2.4.6 |
| 包管理器 | — | `uv`（python3 不含 pip） |
| 额外系统包 | — | `bash`、`tzdata`、`ca-certificates`、`icu-data-en` |
| 内容位置 | `/wheels` | `/usr/lib/python3.14/site-packages` |

## 支持的平台

| 平台 | wheelhouse | runtime | wheel 架构名 |
|---|---|---|---|
| `linux/amd64` | ✓ | ✓ | `x86_64` |
| `linux/arm64` | ✓ | ✓ | `aarch64` |
| `linux/arm/v7` | ✓ | ✓ | `armv7l` |
| `linux/ppc64le` | ✓ | ✓ | `ppc64le` |
| `linux/riscv64` | ✓ | ✓ | `riscv64` |
| `linux/loong64` | ✓ | ✓ | `loongarch64` |

`linux/386`、`linux/arm/v6`、`linux/s390x` 不提供：onnxruntime 在这三个架构上没有可用的
Python 绑定（Alpine 配方 `arch="all !s390x !x86"`；armhf 被 `py3-flatbuffers` 挡住），
而 ddddocr 没有 onnxruntime 就跑不起来。

loong64 构建需 `--build-arg BASE_IMAGE=ghcr.io/loong64/alpine:3.24`（Docker Hub 官方
alpine 无此架构）。

## 镜像体积

| 镜像 | 首次拉取 | 占用磁盘 | 容器内 |
|---|---|---|---|
| `1.6.1-wheelhouse`（arm64） | 80.9 MiB | 170 MB | 86.7 MiB（三个 wheel） |
| `1.6.1`（arm64） | 141.1 MiB | 459 MB | 292 MiB（site-packages 208 MiB） |

`占用磁盘` 取 `docker images` 口径：containerd 计入解压层与压缩 blob 两份。

runtime 镜像的构成（arm64）：

| 内容 | 大小 |
|---|---|
| ddddocr（含 3 个模型，85 MB 中的绝大部分是模型） | 84.9 MB |
| onnxruntime + `onnxruntime.libs` | 53.8 MB |
| numpy | 24.4 MB |
| OpenCV（扩展 1.9 MB + `opencv.libs` 17.9 MB） | 19.8 MB |
| Pillow（`PIL` + `pillow.libs`） | 6.3 MB |

## 产物

```
ddddocr-1.6.1-py3-none-any.whl                       # 纯 python + 模型文件，与架构无关
opencv-4.14.0-cp314-cp314-musllinux_1_2_<arch>.whl
pillow-13.0.0-cp314-cp314-musllinux_1_2_<arch>.whl
SHA256SUMS
system-packages.txt
simple/
  index.html
  <project>/index.html
```

`system-packages.txt` 是上层需要 `apk add` 的包（一行一个，无注释）：`python3` 与 `zlib`。
前者是解释器；后者因为 musllinux 白名单只有 `libc` 与 `libz`，Pillow 与
`libopencv_imgcodecs` 都动态链接了 `libz.so.1`，它不会被收进 `.libs/`。

`simple/` 由 `src/pack_wheel.py --emit-index` 生成，链接为相对路径
（`../../<wheel>#sha256=`），构建期会回读校验每个链接与哈希。

| 标签 | 含义 | PyPI 接受 |
|---|---|---|
| `musllinux_1_2_<arch>` | 在 musl ≥ 1.2 上构建，除 musl 与 libz 外不依赖系统库 | 是 |
| `py3-none-any` | 纯 python，无原生产物 | 是 |
| `linux_<arch>` | 只说明 CPU 架构 | 否 |

## 构建

```bash
# wheelhouse 内容（/wheels）
docker buildx build --platform linux/arm64 --target wheel \
    --output type=local,dest=./dist .

# 可运行镜像
docker buildx build --platform linux/arm64 --target runtime -t ddddocr:1.6.1 .
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `ALPINE_VERSION` | `3.24` | 决定 Python 版本与 wheel 的 `cpXX` tag |
| `BASE_IMAGE` | `alpine:${ALPINE_VERSION}` | loong64 传 `ghcr.io/loong64/alpine:3.24` |
| `ONNX_WHEELHOUSE` | `a76yyyy/onnxruntime:1.24.4-wheelhouse` | onnxruntime / numpy 的来源 |
| `ONNX_VERSION` / `NUMPY_VERSION` | `1.24.4` / `2.4.6` | 与上面的 wheelhouse 内容不一致时构建失败 |
| `OPENCV_VERSION` | `4.14.0` | 源码版本 |
| `OPENCV_CPU_BASELINE` | 空 | `NEON` 让 armv7 的 OpenCV 以 NEON 为基线 |
| `PILLOW_VERSION` | `13.0.0` | 源码版本 |
| `DDDDOCR_REF` | `master` | ddddocr 的 git ref（分支/tag/SHA） |
| `DDDDOCR_VERSION` | 空 | 非空时断言产出的 wheel 版本，与镜像 tag 对齐 |
| `APK_MIRROR` | 空 | 如 `https://mirrors.tuna.tsinghua.edu.cn` |
| `PIP_MIRROR` | 空 | 如 `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `GIT_DOMAIN` | `https://github.com` | 拉 ddddocr 源码的前缀 |

## 已知限制

- `cv2` 是顶层扩展模块（`cv2.cpython-314-<arch>-linux-musl.so`），不是包：OpenCV 的绑定
  在初始化时用写死的 `cv2` 注册子模块，装成 `cv2/cv2.*.so` 会报
  `Bindings generation error`。因此没有 `cv2.data`（haarcascades 等数据文件），自编时也
  只开了 core / imgproc / imgcodecs，没有 video / photo / dnn。
- ddddocr wheel 的 `Requires-Dist: opencv-python-headless` 被改写成 `opencv`（上游写死了
  linux 上的包名，本仓库分发的是自编的 `opencv`）。只改这一条。
- runtime 镜像删除了 `sympy` / `mpmath`：onnxruntime 只用它们做符号形状推断，ddddocr
  不用。因此 `uv pip check` 在镜像里会报这两项缺失。
- armv7 上 OpenCV 默认不带 NEON 基线：`--build-arg OPENCV_CPU_BASELINE=NEON` 可开启，
  但镜像会在无 NEON 的 ARMv7（Armada 370、部分 Cortex-A5）上触发 SIGILL，而验证码
  预处理合计不到 1 ms、收益落在推理之外，故不作默认。
- wheel 的 zip 条目带 mtime，构建不可逐字节复现；内容一致，`sha256` 每次不同。

## 维护者

<details>
<summary>CI 结构</summary>

`.github/workflows/_image.yml` 为共享 workflow，`Build Image.yml` 为调用方，四段：
plan → build → smoke → publish。

- 仅 `workflow_dispatch` 与 tag push 触发
- 每平台一个 job，一次构建两个出口；发布时两个出口各自 `push-by-digest`，artifact 按出口
  分名（`digest-wheelhouse-*` / `digest-runtime-*`），publish 分别合并
- 冒烟直接跑 runtime 镜像：`tests/smoke.py` 校验包版本、无 `/wheels` 残留、cv2/PIL 的
  `ldd`、Pillow 契约、protobuf 来源、原生 ELF 架构，并跑一次真实识别
- 闸门 fail-closed：有发布意图 && build 与 smoke 均 `success` && 平台集合完整，才合并
  manifest；子集构建禁止发布

</details>
