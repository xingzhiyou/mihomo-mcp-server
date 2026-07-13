"""
Config 文件操作与 Mihomo 服务管理。
提供 YAML 配置读写、Mihomo 重启等底层操作。
"""

import os
import subprocess
import tempfile
import shutil
import yaml
import time

from config import MIHOMO_CONFIG, R


def read_config() -> dict | None:
    """读取 config.yaml。异常时返回 None。"""
    try:
        with open(MIHOMO_CONFIG, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def write_config(cfg: dict) -> tuple[bool, str]:
    """原子写入 config.yaml。返回 (成功, 消息)。"""
    fd, tmp_path = tempfile.mkstemp(
        suffix=".yaml", prefix="mihomo_config_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)
        shutil.move(tmp_path, MIHOMO_CONFIG)
        return True, "配置已写入"
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return False, str(e)


def restart_mihomo() -> tuple[bool, str]:
    """重启 Mihomo 并等待就绪。返回 (成功, 消息)。"""
    result = run_systemctl("restart")
    if result.get("success"):
        # 等待服务就绪
        for _ in range(10):
            time.sleep(0.5)
            check = subprocess.run(
                ["sudo", "systemctl", "is-active", "mihomo"],
                capture_output=True, text=True
            )
            if check.stdout.strip() == "active":
                return True, "✅ Mihomo 已重启并就绪"
        return True, "⚠️ 重启命令已发出，但状态检查未返回 active"
    err = result.get("error", {})
    return False, err.get("details", "重启失败") if err else "重启失败"


def run_systemctl(action: str) -> dict:
    """执行 systemctl 操作 (status/start/stop/restart)。"""
    cmd = ["sudo", "systemctl", action, "mihomo"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if action == "status":
            is_active = "Active: active" in stdout \
                        or "active (running)" in stdout
            return R.ok(
                data={
                    "active": is_active,
                    "stdout": stdout[:1000],
                    "stderr": stderr[:500] if stderr else None,
                    "returncode": result.returncode,
                },
                message=f"Mihomo {'运行中' if is_active else '已停止'}"
            )

        if result.returncode == 0:
            msgs = {
                "start": "✅ Mihomo 已启动",
                "stop": "⏹ Mihomo 已停止",
                "restart": "🔄 Mihomo 已重启",
            }
            return R.ok(message=msgs.get(action, f"操作成功: {action}"))

        error_msg = stderr or stdout or f"返回码 {result.returncode}"
        return R.fail(
            "SYSTEMCTL_FAILED",
            f"systemctl {action} 失败",
            details=error_msg[:500],
            suggestions=["检查 sudo 权限", "sudo systemctl status mihomo"]
        )

    except subprocess.TimeoutExpired:
        return R.fail("TIMEOUT", f"systemctl {action} 超时")
    except Exception as e:
        return R.fail("SYSTEMCTL_ERROR",
                       f"systemctl {action} 异常", details=str(e))
