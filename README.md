# Mihomo MCP Server

> 基于 MCP (Model Context Protocol) 的 Mihomo/Clash Meta 代理节点管理服务。  
> 让 AI 助手能自动管理代理节点、订阅、服务控制与内核版本。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

---

## ✨ 功能一览

### 🌐 节点管理（6 工具）
| 工具 | 说明 |
|:----|:-----|
| `list_groups` | 列出所有代理组及当前节点 |
| `list_nodes` | 列出指定组的节点详情与延迟 |
| `switch_node` | 切换代理组节点 |
| `test_delay` | 测试单个节点延迟 |
| `test_connectivity` | 测试当前代理下目标网站可达性 |
| `batch_test` | 遍历所有节点，自动推荐最快节点 |

### 📡 订阅管理（5 工具）
| 工具 | 说明 |
|:----|:-----|
| `list_subscriptions` | 列出订阅详情（节点数、流量、到期时间） |
| `refresh_subscription` | 刷新订阅节点列表 |
| `add_subscription` | 添加新订阅（自动重启 Mihomo） |
| `modify_subscription` | 修改订阅参数 |
| `delete_subscription` | 删除订阅（清理引用 + 本地文件） |

### 🛠 服务控制（3 工具）
| 工具 | 说明 |
|:----|:-----|
| `mihomo_status` | 查看 Mihomo 服务状态（含版本、API 可达性） |
| `mihomo_start` | 启动 Mihomo 服务 |
| `mihomo_stop` | 停止 Mihomo 服务 |

### 🔄 内核版本管理（4 工具）
| 工具 | 说明 |
|:----|:-----|
| `mihomo_version` | 查看当前版本与更新状态 |
| `mihomo_list_versions` | 列出所有可用版本 |
| `mihomo_upgrade` | 升级/降级到指定版本 |
| `mihomo_rollback` | 回滚到备份版本 |

---

## 🚀 快速开始

```bash
# 一键部署（自动安装 Mihomo + 启动 MCP）
python3 main.py --install

# 仅启动 MCP 服务（Mihomo 已就绪时）
python3 main.py --mcp-only

# 正常启动 MCP 服务器
python3 main.py
```

### 环境要求

- **Python** ≥ 3.10
- **sudo 权限**（安装二进制、管理 systemd 服务）
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
├── main.py               # 入口（3 模式：正常 / --install / --mcp-only）
├── install.py            # 📦 一键部署脚本
├── config.py             # 配置常量 + 结构化错误响应类
├── mihomo_api.py         # Mihomo REST API 封装
├── config_manager.py     # YAML 配置读写 + systemctl 管理
├── tools_nodes.py        # 🌐 节点管理工具
├── tools_subscriptions.py # 📡 订阅管理工具
├── tools_versions.py     # 🛠 服务控制 + 内核版本管理
├── server.py             # MCP HTTP 服务器（SSE 协议）
├── pyproject.toml        # 项目元数据
├── LICENSE               # MIT 协议
├── README.md             # 本文档
└── .gitignore
```

---

## 🔌 MCP 协议

服务使用 **SSE (Server-Sent Events)** 协议：

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
| `MIHOMO_API` | `http://127.0.0.1:9090` | Mihomo 外部控制器地址 |
| `MIHOMO_CONFIG` | `/etc/mihomo/config.yaml` | Mihomo 配置文件路径 |
| `GITHUB_TOKEN` | `""` | GitHub API Token（提升限额至 5000次/小时） |

---

## 🔐 权限说明

部署和运行过程中需要以下权限：

- **sudo**: 安装二进制、管理 systemd 服务、读写 `/etc/mihomo/`
- **systemd**: 管理 Mihomo 服务启停
- **端口 9010**: MCP 服务器监听
- **端口 9090**: Mihomo API（需与 Mihomo 配置一致）

---

## 📦 一键部署（`install.py`）

```bash
python3 install.py              # 完整部署
python3 install.py --dry-run    # 仅检测，不操作
python3 install.py --mcp-only   # 仅启动 MCP
```

部署流程：

```
[1/7] 检测     → 检查 Mihomo 是否已安装
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
```

---

## 📄 许可证

[MIT](LICENSE) © 2026 星之游

---

## 🙏 致谢

- [MetaCubeX/mihomo](https://github.com/MetaCubeX/mihomo) — Mihomo/Clash Meta 内核
- [MCP Protocol](https://modelcontextprotocol.io/) — Model Context Protocol
