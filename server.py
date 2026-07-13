"""
MCP HTTP 服务器：路由分发、SSE 协议、工具注册。
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

from config import R, MIHOMO_API
from tools_nodes import (
    tool_list_groups, tool_list_nodes, tool_switch_node,
    tool_test_delay, tool_test_connectivity, tool_batch_test,
)
from tools_subscriptions import (
    tool_list_subscriptions, tool_refresh_subscription,
    tool_add_subscription, tool_modify_subscription,
    tool_delete_subscription,
)
from tools_versions import (
    tool_mihomo_status, tool_mihomo_start, tool_mihomo_stop,
    tool_mihomo_version, tool_mihomo_list_versions,
    tool_mihomo_upgrade, tool_mihomo_rollback,
)

# ─── 工具注册 ──────────────────────────────────────

MCP_TOOLS = {
    # 节点管理 ──
    "list_groups": {
        "name": "list_groups",
        "description": "列出所有代理组及其当前选择的节点",
        "handler": tool_list_groups,
        "parameters": {}
    },
    "list_nodes": {
        "name": "list_nodes",
        "description": "列出指定代理组的节点及延迟。不指定则列出所有组",
        "handler": tool_list_nodes,
        "parameters": {
            "group": {"type": "string",
                      "description": "代理组名称（可选）",
                      "required": False}
        }
    },
    "switch_node": {
        "name": "switch_node",
        "description": "切换指定代理组的节点",
        "handler": tool_switch_node,
        "parameters": {
            "group": {"type": "string",
                      "description": "代理组名称",
                      "required": True},
            "node": {"type": "string",
                     "description": "目标节点名称（注意拼写需完全一致）",
                     "required": True}
        }
    },
    "test_delay": {
        "name": "test_delay",
        "description": "测试指定代理节点的延迟",
        "handler": tool_test_delay,
        "parameters": {
            "node": {"type": "string",
                     "description": "节点名称", "required": True},
            "url": {"type": "string",
                    "description": "测试目标URL", "required": False},
            "timeout": {"type": "number",
                        "description": "超时时间(ms)", "required": False}
        }
    },
    "test_connectivity": {
        "name": "test_connectivity",
        "description": "测试当前代理下能否访问指定目标URL",
        "handler": tool_test_connectivity,
        "parameters": {
            "target": {"type": "string",
                       "description": "测试目标URL", "required": False}
        }
    },
    "batch_test": {
        "name": "batch_test",
        "description": "遍历各节点逐一测试目标连通性，推荐最快节点（会依次切换节点，耗时较长）",
        "handler": tool_batch_test,
        "parameters": {
            "target": {"type": "string",
                       "description": "测试目标URL", "required": False}
        }
    },
    # 订阅管理 ──
    "list_subscriptions": {
        "name": "list_subscriptions",
        "description": "列出所有订阅的详细信息，包括节点数、流量使用情况、到期时间",
        "handler": tool_list_subscriptions,
        "parameters": {}
    },
    "refresh_subscription": {
        "name": "refresh_subscription",
        "description": "刷新/更新指定订阅（从远程重新下载节点列表）",
        "handler": tool_refresh_subscription,
        "parameters": {
            "name": {"type": "string",
                     "description": "订阅名称，默认 sub",
                     "required": False}
        }
    },
    "add_subscription": {
        "name": "add_subscription",
        "description": "添加新的订阅。需要名称和URL。use_proxy控制是否走代理下载。添加后自动重启Mihomo",
        "handler": tool_add_subscription,
        "parameters": {
            "name": {"type": "string",
                     "description": "订阅名称（英文/数字，唯一标识）",
                     "required": True},
            "url": {"type": "string",
                    "description": "订阅链接（https://...）",
                    "required": True},
            "use_proxy": {"type": "boolean",
                          "description": "是否通过代理下载（默认 true）",
                          "required": False},
            "interval": {"type": "number",
                         "description": "更新间隔秒数（默认 3600）",
                         "required": False}
        }
    },
    "modify_subscription": {
        "name": "modify_subscription",
        "description": "修改已有订阅的URL/代理方式/更新间隔/重命名。只填要改的字段",
        "handler": tool_modify_subscription,
        "parameters": {
            "name": {"type": "string",
                     "description": "要修改的订阅名称",
                     "required": True},
            "url": {"type": "string",
                    "description": "新订阅链接（不填不修改）",
                    "required": False},
            "use_proxy": {"type": "boolean",
                          "description": "True走代理/False直连（不填不修改）",
                          "required": False},
            "interval": {"type": "number",
                         "description": "新更新间隔秒数（0不修改）",
                         "required": False},
            "new_name": {"type": "string",
                         "description": "重命名（可选）",
                         "required": False}
        }
    },
    "delete_subscription": {
        "name": "delete_subscription",
        "description": "删除指定订阅（自动移除代理组引用并重启Mihomo）",
        "handler": tool_delete_subscription,
        "parameters": {
            "name": {"type": "string",
                     "description": "订阅名称",
                     "required": True}
        }
    },
    # 服务控制 ──
    "mihomo_status": {
        "name": "mihomo_status",
        "description": "查看Mihomo服务的详细状态（运行中/已停止、版本、API可达性）",
        "handler": tool_mihomo_status,
        "parameters": {}
    },
    "mihomo_start": {
        "name": "mihomo_start",
        "description": "启动Mihomo代理服务",
        "handler": tool_mihomo_start,
        "parameters": {}
    },
    "mihomo_stop": {
        "name": "mihomo_stop",
        "description": "停止Mihomo代理服务",
        "handler": tool_mihomo_stop,
        "parameters": {}
    },
    # 内核版本管理 ──
    "mihomo_version": {
        "name": "mihomo_version",
        "description": "查看当前安装的Mihomo内核版本及更新状态",
        "handler": tool_mihomo_version,
        "parameters": {}
    },
    "mihomo_list_versions": {
        "name": "mihomo_list_versions",
        "description": "列出Mihomo所有可用版本（含版本号、发布时间、大小、是否为当前版本）",
        "handler": tool_mihomo_list_versions,
        "parameters": {}
    },
    "mihomo_upgrade": {
        "name": "mihomo_upgrade",
        "description": "升级或降级Mihomo内核到指定版本（默认升级到最新版）",
        "handler": tool_mihomo_upgrade,
        "parameters": {
            "version": {"type": "string",
                        "description": "目标版本号，如 v1.19.28 或 latest",
                        "required": False},
            "force": {"type": "boolean",
                      "description": "如果目标版本与当前相同，设为true强制重装",
                      "required": False}
        }
    },
    "mihomo_rollback": {
        "name": "mihomo_rollback",
        "description": "回滚Mihomo到备份版本（仅在上次升级操作后可用）",
        "handler": tool_mihomo_rollback,
        "parameters": {}
    },
}


# ─── SSE 事件流 ────────────────────────────────────

def _sse_format(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


# ─── HTTP 处理器 ──────────────────────────────────

class MCPHandler(BaseHTTPRequestHandler):
    """MCP over SSE 协议处理器"""

    def log_message(self, format, *args):
        pass  # 抑制默认日志

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok", "service": "mcp-nodes",
                             "tools": len(MCP_TOOLS)})
            return

        if self.path == "/mcp/sse":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            # 发送 endpoint 事件
            msg = json.dumps({"endpoint": "/mcp/message"})
            self.wfile.write(
                _sse_format("endpoint", msg).encode()
            )

            # 发送工具列表
            tools_info = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"]
                }
                for t in MCP_TOOLS.values()
            ]
            self.wfile.write(
                _sse_format("tools",
                            json.dumps({"tools": tools_info})).encode()
            )

            # 保持连接
            try:
                while True:
                    self.wfile.write(b": keepalive\n\n")
                    import time
                    time.sleep(15)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        self._send_json({"error": "not_found"}, 404)

    def do_POST(self):
        if self.path == "/mcp/message":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
            except Exception:
                self._send_json({"error": "invalid_json"}, 400)
                return

            tool_name = body.get("tool", "")
            params = body.get("parameters", {})

            if tool_name not in MCP_TOOLS:
                self._send_json({
                    "error": {
                        "code": "UNKNOWN_TOOL",
                        "message": f"未知工具: {tool_name}",
                        "suggestions": [
                            f"可用工具: {list(MCP_TOOLS.keys())}"
                        ]
                    }
                }, 404)
                return

            handler = MCP_TOOLS[tool_name]["handler"]
            try:
                result = handler(**params)
                self._send_json({
                    "result": result,
                    "tool": tool_name
                })
            except Exception as e:
                tb = __import__("traceback").format_exc()
                self._send_json({
                    "result": R.fail(
                        "HANDLER_ERROR",
                        f"工具 '{tool_name}' 执行异常",
                        details=f"{type(e).__name__}: {e}\n{tb[:500]}",
                        suggestions=["检查参数类型", "查看服务端日志"]
                    ),
                    "tool": tool_name
                }, 500)
            return

        self._send_json({"error": "not_found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Authorization")
        self.end_headers()


def run_server(port: int = 9010):
    """启动 MCP HTTP 服务器。"""
    server = HTTPServer(("0.0.0.0", port), MCPHandler)
    print(f"🚀 MCP Node Manager v2.2 启动于端口 {port}")
    print(f"📋 工具数: {len(MCP_TOOLS)}")
    print(f"📡 SSE: http://127.0.0.1:{port}/mcp/sse")
    print(f"🩺 Health: http://127.0.0.1:{port}/health")
    server.serve_forever()
