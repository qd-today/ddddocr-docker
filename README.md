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

- `latest` 标签：跟随上游 master 自动构建（workflow_dispatch 触发）
- 版本号标签（如 `1.6.1`）：与 ddddocr 上游版本对齐，构建时使用 `ddddocr.version` 中锁定的 commit，可复现
- 发布新版本流程：更新 `ddddocr.version` 为上游目标 commit → 打对应版本 tag → CI 自动构建并推送

## **Tips**

> Onnxruntime Builder does not currently support building i386 and s390x wheels!

## **构建说明**

- OpenCV 不采用 apk 的 py3-opencv：其 Qt/OpenGL/FFmpeg 依赖链约 236MB，ddddocr 用不到；且 PyPI 无 musllinux wheel，故改为源码编译
- 编译产物经 `strip --strip-unneeded` 剥离符号，amd64/arm64 镜像约 460MB
- 体积优化（约 50MB 死重清理，不影响任何功能）：不安装 bash/file（busybox sh 足够）、git 归入 .build_deps 用完即卸、删除 OpenCV haarcascades/lbpcascades 级联数据与 `/usr/include` 头文件、清 sympy/mpmath 元数据残留与 numpy 测试套件
- 本地构建加速：`docker build --build-arg APK_MIRROR=https://mirrors.tuna.tsinghua.edu.cn .`
