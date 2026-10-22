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
- DDDDOCR_VERSION == 1.6.1（上游未打版本 tag，发布时以 `ddddocr.version` 文件锁定 commit SHA）

## **版本策略**

- `latest` 标签：跟随上游 master 自动构建（workflow_dispatch 触发）
- 版本号标签（如 `1.6.1`）：与 ddddocr 上游版本对齐，构建时使用 `ddddocr.version` 中锁定的 commit，可复现
- 发布新版本流程：更新 `ddddocr.version` 为上游目标 commit → 打对应版本 tag → CI 自动构建并推送

## **Tips**

> Onnxruntime Builder does not currently support building i386 and s390x wheels!
