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
# syntax=docker/dockerfile:1.7
FROM alpine:3.24
RUN --mount=type=bind,from=a76yyyy/ddddocr:wheelhouse,source=/wheels,target=/w1 \
    --mount=type=bind,from=a76yyyy/onnxruntime:wheelhouse,source=/wheels,target=/w2 \
    apk add --no-cache $(cat /w1/system-packages.txt) uv && \
    uv pip install --system --break-system-packages --no-cache \
        --index-url https://pypi.org/simple \
        --extra-index-url file:///w1/simple \
        --extra-index-url file:///w2/simple \
        "ddddocr==1.6.1" "opencv-python-headless==4.14.0" "pillow==13.0.0" \
        "onnxruntime==1.24.4" "numpy==2.4.6"
```

| 写法 | 原因 |
|---|---|
| `apk add $(cat /w1/system-packages.txt)` | 清单是 wheelhouse 的运行时前置条件（解释器与 `libz`），写错会在这里构建失败 |
| `--index-url https://pypi.org/simple` | 默认索引是**最低**优先级，纯 Python 依赖（flatbuffers / packaging / protobuf / sympy）从这里兜底 |
| `--extra-index-url file:///wN/simple` | 每个 wheelhouse 一个，按定义顺序查询；first-index 策略下第一个含该包的索引胜出。实测（往本地 wheel 里塞标记文件后安装）：本地那份一定被选中 |
| 发行名与 PyPI 同名 | wheelhouse 里的 wheel 用 PyPI 同名发行名（如 `opencv-python-headless`），用户换回 PyPI 版不用改任何配置；功能差异只在本仓库刻意裁剪的那部分 |

`/w1/simple` 是 PEP 503 索引，链接为相对路径，可与 wheel 目录一起挂到任意位置。## 镜像内容

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
| `1.6.1-wheelhouse`（arm64） | 80.9 MiB | 170 MB | 81 MiB（三个 wheel） |
| `1.6.1`（arm64） | 141.1 MiB | 459 MB | 296 MiB（site-packages 208 MiB） |

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
  影响面：级联分类器（人脸、眼睛检测）不可用，`cv2.data` 属性不存在，`import cv2.cv2` 不可用；
  文字识别不依赖这些，ddddocr 自身代码未引用 `cv2.data` 或级联文件。
- 自编 OpenCV 沿用 `opencv-python-headless` 这个发行名：官方四个包（`opencv-python` /
  `opencv-contrib-python` / `opencv-python-headless` / `opencv-contrib-python-headless`）
  里，它是「无 GUI / 无后端」的那一个，正是容器场景要的。
  **但它不是官方版的等价物**：官方 headless 版是完整模块（video / photo / dnn 等俱全），
  本仓库只保留 core / imgproc / imgcodecs，也没有 `cv2.data` 的级联文件。
  发行名保持一致的意义是：用户改从 PyPI 安装同名包，就换回功能完整的官方版，配置不用动。

## 维护者

<details>
<summary>版本参数</summary>

上游发新版时，改这里或 dispatch 时传同名输入即可构建新版本；产物版本与传入版本不一致时
构建失败（`--expect-version` 断言）。

| 参数 | 作用 | 默认值 |
|---|---|---|
| `opencv_version` | OpenCV 源码版本（自编最小化 wheel） | 4.14.0 |
| `pillow_version` | Pillow 源码版本（自编 wheel，不链 libimagequant） | 13.0.0 |
| `ddddocr_version` | ddddocr 版本，同时是 runtime 镜像的 tag | 跟随 git ref |
| `ddddocr_ref` | ddddocr 的 git ref（分支 / tag / SHA） | 上游默认分支 |
| `onnx_version` | onnxruntime 版本，同时决定用哪个 wheelhouse 镜像 | 1.24.4 |
| `numpy_version` | numpy 版本（由 onnxruntime 的 wheelhouse 提供） | 2.4.6 |
| `alpine_version` | alpine 版本，决定 Python 小版本与 wheel 的 cpXX tag | 3.24 |

`onnxruntime` 与 `numpy` 来自 Alpine 的 apk 预编译包，版本受 apk 仓限制：参数只能钉住 apk
里已有的版本，apk 更新后再改这里（版本对不上时构建会在断言处失败，不会产出错标版本的 wheel）。

</details>

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
