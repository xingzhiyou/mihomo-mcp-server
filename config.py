"""
配置常量与结构化结果工具类。
"""

import os
from typing import Any

# ─── 配置 ───────────────────────────────────────────
MIHOMO_API = os.environ.get("MIHOMO_API", "http://127.0.0.1:9090")
MIHOMO_CONFIG = os.environ.get("MIHOMO_CONFIG", "/etc/mihomo/config.yaml")
TEST_URL = "https://www.gstatic.com/generate_204"
TEST_TIMEOUT = 5000  # ms
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")


class R:
    """统一结构化响应。所有工具返回 R.ok() 或 R.fail(...)"""

    @staticmethod
    def ok(data: Any = None, message: str = "") -> dict:
        return {
            "success": True, "data": data, "message": message,
            "error": None
        }

    @staticmethod
    def fail(code: str, message: str, details: str = "",
             suggestions: list | None = None,
             affected: list | None = None) -> dict:
        return {
            "success": False, "data": None, "message": message,
            "error": {
                "code": code, "message": message, "details": details,
                "suggestions": suggestions or [],
                "affected": affected or []
            }
        }

    @staticmethod
    def not_found(kind: str, name: str,
                  available: list | None = None) -> dict:
        return R.fail(
            code=f"{kind.upper()}_NOT_FOUND",
            message=f"未找到{kind}: {name}",
            details=f"请求的 {kind} '{name}' 不存在",
            suggestions=[f"检查 {kind} 名称是否正确",
                         f"使用 list_{kind}s 查看可用列表"],
            affected=available or []
        )

    @staticmethod
    def invalid_param(param: str, reason: str,
                      example: str = "") -> dict:
        return R.fail(
            code="INVALID_PARAMETER",
            message=f"参数 '{param}' 无效: {reason}",
            suggestions=[f"检查 {param} 的格式"] +
                        ([f"参考: {example}"] if example else []),
            affected=[param]
        )

    @staticmethod
    def api_error(endpoint: str, detail: str) -> dict:
        return R.fail(
            code="MIHOMO_API_ERROR",
            message=f"Mihomo API 调用失败: {endpoint}",
            details=detail,
            suggestions=["检查 Mihomo 是否在运行: systemctl status mihomo",
                         f"尝试直接访问: {MIHOMO_API}{endpoint}"],
            affected=[endpoint]
        )

    @staticmethod
    def config_error(detail: str) -> dict:
        return R.fail(
            code="CONFIG_ERROR",
            message="配置文件操作失败",
            details=detail,
            suggestions=["检查 config.yaml 权限",
                         f"手动检查: sudo cat {MIHOMO_CONFIG}"],
            affected=[MIHOMO_CONFIG]
        )

    @staticmethod
    def restart_fail(detail: str) -> dict:
        return R.fail(
            code="RESTART_FAILED",
            message="Mihomo 重启失败",
            details=detail,
            suggestions=["尝试手动重启: sudo systemctl restart mihomo",
                         "检查日志: sudo journalctl -u mihomo -n 20"],
            affected=["systemctl"]
        )

    @staticmethod
    def timeout(operation: str, seconds: int) -> dict:
        return R.fail(
            code="TIMEOUT",
            message=f"操作超时: {operation}",
            details=f"超过 {seconds} 秒未响应",
            suggestions=["检查网络连接", "换一个节点试试", "增大 timeout 参数"],
            affected=[operation]
        )

    @staticmethod
    def already_exists(kind: str, name: str) -> dict:
        return R.fail(
            code=f"{kind.upper()}_ALREADY_EXISTS",
            message=f"{kind} '{name}' 已存在",
            suggestions=[f"使用 modify_{kind} 修改",
                         f"使用不同的名称或先删除: delete_{kind} {name}"],
            affected=[name]
        )
