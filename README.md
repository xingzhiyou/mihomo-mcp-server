# Mihomo MCP Server

> 基于 MCP (Model Context Protocol) 的 Mihomo/Clash Meta 代理管理服务。  
> 让 AI 助手能自动管理系统代理、工具代理、订阅、规则与内核版本。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

---

## ✨ 功能一览

### ⚡ Mihomo 管理（12 工具）

| 工具 | 说明 |
|:----|:-----|
| `mihomo_status` | 查看 Mihomo 服务状态（版本、API 可达性） |
| `mihomo_start` / `mihomo_stop` | 启动/停止 Mihomo 服务 |
| `mihomo_version` | 查看当前版本与更新状态 |
| `mihomo_list_versions` | 列出所有可用版本 |
| `mihomo_upgrade` | 升级/降级到指定版本 |
| `mihomo_rollback` | 回滚到备份版本 |
| `list_subscriptions` | 列出订阅详情（节点数、流量、到期时间） |
| `refresh_subscription` | 刷新订阅节点列表 |
| `add_subscription` | 添加新订阅（自动重启 Mihomo） |
| `modify_subscription` | 修改订阅参数 |
| `delete_subscription` | 删除订阅（清理引用 + 本地文件） |

### 🌐 系统代理（11 工具）

| 工具 | 说明 |
|:----|:-----|
| `list_groups` | 列出所有代理组及当前节点 |
| `list_nodes` | 列出指定组的节点详情与延迟（并发测试） |
| `switch_node` | 切换代理组节点 |
| `test_delay` | 测试单个节点延迟 |
| `test_connectivity` | 测试目标网站可达性 |
| `batch_test` | 遍历节点，自动推荐最快节点 |
| `list_rules` | 列出所有路由规则 |
| `add_rule` | 添加路由规则（DOMAIN/IP-CIDR/GEOIP 等） |
| `remove_rule` | 删除路由规则 |
| `add_direct_rule` | 快捷添加直连规则 |
| `add_proxy_rule` | 快捷添加代理规则 |

### 🔧 工具代理（7 工具）

独立 Mihomo 实例（端口 7893），与系统代理完全隔离。

| 工具 | 说明 |
|:----|:-----|
| `toolproxy_status` | 查看工具代理运行状态 |
| `toolproxy_init` | 初始化工具代理配置 |
| `toolproxy_start` / `toolproxy_stop` | 启动/停止工具代理 |
| `toolproxy_switch_node` | 切换工具代理节点 |
| `toolproxy_list_nodes` | 列出工具代理可用节点 |
| `run_with_node` | **在指定节点下执行命令，不影响系统代理，5 分钟空闲自动关闭** |

---

## 🚀 快速开始

```bash
# 正常启动 MCP 服务器
python3 main.py

# 一键部署（自动安装 Mihomo + 启动 MCP）
python3 main.py --install

# 仅启动 MCP（Mihomo 已就绪时）
python3 main.py --mcp-only
```

### 环境要求

- **Python** ≥ 3.10
- **sudo 权限**（管理 systemd 服务）
- **systemd**（Mihomo 服务管理）
- **screen**（MCP 服务守护）

### 依赖安装

```bash
pip install pyyaml>=6.0
```

---

## 🏗 项目结构

```
mcp_nodes/
├── main.py                  # 入口（3 模式）
├── server.py                # MCP HTTP 服务器（SSE 协议，工具注册）
├── config.py                # 配置常量 + 结构化响应类
├── mihomo_api.py            # Mihomo REST API 封装（含 API Secret 支持）
├── config_manager.py        # YAML 原子读写 + systemctl 管理
├── tools_nodes.py           # 🌐 节点管理工具（并发测试）
├── tools_rules.py           # 📋 规则管理工具
├── tools_subscriptions.py   # 📡 订阅管理工具
├── tools_versions.py        # 🛠 服务控制 + 版本管理
├── tools_toolproxy.py       # 🔧 工具代理（独立 Mihomo 实例，空闲自动停止）
├── install.py               # 📦 一键部署脚本
├── push.py                  # Git 推送脚本（环境变量读取 Token）
├── pyproject.toml           # 项目元数据
├── LICENSE                  # MIT 协议
└── README.md                # 本文档
```

---

## 🔌 MCP 协议

服务使用 **SSE** 协议，绑定 `127.0.0.1`（仅本地访问）：

```
SSE 端点: http://127.0.0.1:9010/mcp/sse
消息端点: http://127.0.0.1:9010/mcp/message
健康检查: http://127.0.0.1:9010/health
```

### 调用示例

```bash
curl -X POST http://127.0.0.1:9010/mcp/message \
  -H "Content-Type: application/json" \
  -d '{"tool": "list_groups", "parameters": {}}'
```

### 响应格式

所有工具返回统一结构化响应：

```json
{
  "success": true,
  "data": { ... },
  "message": "操作成功",
  "error": null
}
```

错误时：

```json
{
  "success": false,
  "data": null,
  "message": "错误描述",
  "error": {
    "code": "ERROR_CODE",
    "details": "详细信息",
    "suggestions": ["建议1", "建议2"]
  }
}
```

---

## ⚙ 配置

通过环境变量配置：

| 变量 | 默认值 | 说明 |
|:----|:------|:-----|
| `MIHOMO_API` | `http://127.0.0.1:9090` | 系统 Mihomo 外部控制器地址 |
| `MIHOMO_CONFIG` | `/etc/mihomo/config.yaml` | 系统 Mihomo 配置文件路径 |
| `GITHUB_TOKEN` | `""` | GitHub API Token（版本管理用） |

### 工具代理端口

| 端口 | 说明 |
|:----:|:------|
| 7893 | 工具代理 HTTP/SOCKS5 混合端口 |
| 9092 | 工具代理外部控制器 API |

---

## 🔐 安全说明

- **MCP 服务器** 绑定 `127.0.0.1:9010`，仅本地访问
- **工具代理** 仅本地端口 7893/9092
- **系统 Mihomo API** 自动读取 `config.yaml` 中的 `secret` 配置，如果设置了 secret 则所有 API 请求自动带上 Bearer Token
- **push.py** 从环境变量 `GITHUB_TOKEN` 读取 Token，不硬编码

---

## 📦 一键部署（`install.py`）

```bash
python3 install.py              # 完整部署
python3 install.py --dry-run    # 仅检测，不操作
python3 install.py --mcp-only   # 仅启动 MCP
```

部署流程：

```
[1/7] 检测 confiug → 检查 Mihomo 安装状态
[2/7] 下载     → GitHub 获取最新内核
[3/7] 安装     → 备份旧版 + 安装新版
[4/7] 配置     → 创建基础 config.yaml
[5/7] 服务     → 创建 systemd 服务
[6/7] 启动     → 启动 + 验证 API
[7/7] MCP      → 启动 MCP 服务器
```

---

## 🧪 测试

```bash
# 健康检查
curl http://127.0.0.1:9010/health

# 列出代理组
curl -X POST http://127.0.0.1:9010/mcp/message \
  -H "Content-Type: application/json" \
  -d '{"tool": "list_groups", "parameters": {}}'

# 工具代理运行状态
curl -X POST http://127.0.0.1:9010/mcp/message \
  -H "Content-Type: application/json" \
  -d '{"tool": "toolproxy_status", "parameters": {}}'
```

---

## 📄 许可证

[MIT](LICENSE) © 2026 星之游

---

## 🙏 致谢

- [MetaCubeX/mihomo](https://github.com/MetaCubeX/mihomo) — Mihomo/Clash Meta 内核
- [MCP Protocol](https://modelcontextprotocol.io/) — Model Context Protocol
