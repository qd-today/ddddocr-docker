#!/usr/bin/env python3
"""本仓 CI 脚本的本地自测：不依赖网络与 Docker。

跑法：python3 .github/workflows/scripts/selftest.py

覆盖：
  1. plan.py 的输出键（workflow 的 job outputs 依赖这些名字）
  2. 标签归属：tag 推送才产出正式标签与 latest，其余只推进 dev
  3. cache scope 带上了 cache_bust，否则传了等于没传
  4. README 的标签章节与 CI 行为一致
"""
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
FAILURES = []

PLAN_KEYS = ['expected', 'full', 'runtime_matrix', 'smoke_matrix', 'wheel_matrix', 'ddddocr_ref', 'version']
REPO_NAME = "ddddocr-docker"
DEV_TAGS = ['dev']


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{(' — ' + detail) if detail and not cond else ''}")
    if not cond:
        FAILURES.append(label)


def test_plan_output_keys():
    print("plan.py 的输出键:")
    # 只做静态检查：plan.py 依赖多个环境变量，本地跑不起来也不该因此漏检
    src = (HERE / "plan.py").read_text()
    keys = set(re.findall(r"""print\(\s*['"]([\w-]+)=['"]""", src))
    keys |= set(re.findall(r"""print\(\s*['"]([\w-]+)=%""", src))
    for k in PLAN_KEYS:
        check(f"plan.py 输出 {k}", k in keys, f"实际 {sorted(keys)}")



def test_tag_assignment():
    print("标签归属:")
    lines = (ROOT / ".github/workflows/_image.yml").read_text().split("\n")
    starts = [k for k, l in enumerate(lines)
              if "startsWith(github.ref" in l and "refs/tags/" in l and l.strip().startswith("if ")]
    if not starts:
        check("找得到 tag 分支", False, "没有 startsWith(github.ref, 'refs/tags/') 的 if")
        return
    check("找得到 tag 分支", True)
    i = starts[0]
    depth, else_i, fi_i = 0, None, None
    for k in range(i, len(lines)):
        t = lines[k].strip()
        if t.startswith("if "):
            depth += 1
        elif t == "else" and depth == 1:
            else_i = k
        elif t == "fi":
            depth -= 1
            if depth == 0:
                fi_i = k
                break
    if else_i is None or fi_i is None:
        check("tag 分支有 else 与 fi", False)
        return
    tag_part = "\n".join(lines[i:else_i])
    else_part = "\n".join(lines[else_i:fi_i])
    # latest 可能写字面量，也可能来自 inputs.latest_tags 参数
    check("tag 推送产出 latest", "latest" in tag_part or "LATEST_TAGS" in tag_part,
          tag_part.strip()[:100])
    check("tag 推送产出版本号", "VERSION" in tag_part, tag_part.strip()[:100])
    check("非 tag 分支不产出 latest",
          "latest" not in else_part and "LATEST_TAGS" not in else_part,
          else_part.strip()[:120])
    check("非 tag 分支产出 dev", "dev" in else_part, else_part.strip()[:120])



def test_cache_bust_wired():
    print("cache_bust 接线:")
    lines = (ROOT / ".github/workflows/_image.yml").read_text().split("\n")
    scopes = [l for l in lines if "scope=" in l]
    check("存在 cache scope", bool(scopes))
    bad = [l.strip()[:90] for l in scopes if "cache_bust" not in l]
    check("每个 cache scope 都带 cache_bust", not bad, f"未带的: {bad[:2]}")



def test_readme_mentions_dev():
    print("README 标签章节:")
    readme = (ROOT / "README.md").read_text()
    i = readme.find("## 标签")
    check("README 有标签章节", i >= 0)
    if i < 0:
        return
    j = readme.find("\n## ", i + 5)
    section = readme[i:j if j > 0 else len(readme)]
    for t in DEV_TAGS:
        check(f"标签章节提到 {t}", t in section)
    check("标签章节说明 latest 只由 tag 产出", "tag 推送" in section)




def test_script_jobs_have_checkout():
    print("跑脚本的 job 要先 checkout:")
    for wf in sorted((ROOT / ".github/workflows").glob("*.yml")):
        text = wf.read_text()
        if "scripts/" not in text:
            continue
        blocks = re.split(r"(?m)^  (?=\w)", text)
        for block in blocks:
            job = block.split("\n", 1)[0].rstrip(":").strip()
            if "scripts/" not in block:
                continue
            lines = block.split("\n")
            co = next((k for k, l in enumerate(lines) if "actions/checkout" in l), None)
            sc = next((k for k, l in enumerate(lines) if "scripts/" in l), None)
            if co is None:
                check(f"{wf.name} / {job}: 跑脚本但没有 checkout", False)
            elif sc is not None and sc < co:
                check(f"{wf.name} / {job}: 脚本在 checkout 之前执行", False,
                      "工作目录里还没有仓库文件，脚本会找不到")
            else:
                check(f"{wf.name} / {job}: 先 checkout 再跑脚本", True)

def main():
    test_plan_output_keys()
    test_tag_assignment()
    test_cache_bust_wired()
    test_readme_mentions_dev()
    test_script_jobs_have_checkout()
    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} 项 -> {FAILURES}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
