#!/usr/bin/env python3
"""Git HTTPS 推送脚本，通过 GIT_ASKPASS 处理认证。"""
import os, sys, stat, subprocess, tempfile

TOKEN_ENV = "GITHUB_TOKEN"

def main():
    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"❌ 环境变量 {TOKEN_ENV} 未设置", file=sys.stderr)
        sys.exit(1)
    fd, askpass = tempfile.mkstemp(prefix="git_askpass_", suffix=".sh")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("#!/bin/sh\necho '" + token + "'\n")
        os.chmod(askpass, stat.S_IRWXU)
        env = os.environ.copy()
        env["GIT_ASKPASS"] = askpass
        result = subprocess.run(
            ["git", "push", "https://github.com/xingzhiyou/mihomo-mcp-server.git"],
            capture_output=True, text=True, timeout=60, env=env
        )
        if result.returncode == 0:
            print("✅ 推送成功")
        else:
            print(f"❌ 推送失败:\n{result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
    finally:
        os.unlink(askpass)

if __name__ == "__main__":
    main()
