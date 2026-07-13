#!/usr/bin/env python3
"""
MCP Server: Proxy Node Manager v2.2
模块化重构版。单文件 → 多模块拆分：

  config.py         配置常量与结构化结果工具类
  mihomo_api.py     Mihomo REST API 封装
  config_manager.py Config 文件操作与 Mihomo 服务管理
  tools_nodes.py    节点管理工具（6个）
  tools_subscriptions.py  订阅管理工具（5个）
  tools_versions.py 服务控制（3个）与内核版本管理（4个）
  server.py         MCP HTTP 服务器 + 工具注册 + 路由
  main.py           入口
  install.py        📦 一键部署脚本（自动安装 Mihomo + 启动 MCP）

用法:
  python3 main.py             启动 MCP 服务器
  python3 main.py --install   一键部署（安装Mihomo + 启动MCP）
  python3 main.py --mcp-only  仅启动MCP
"""

import sys
from server import run_server

if __name__ == "__main__":
    if "--install" in sys.argv:
        from install import main as installer
        installer()
    elif "--mcp-only" in sys.argv:
        from install import step7_setup_mcp
        step7_setup_mcp()
    elif "--dry-run" in sys.argv or "-n" in sys.argv:
        from install import main as installer
        sys.argv = [sys.argv[0], "--dry-run"]
        installer()
    else:
        run_server()
