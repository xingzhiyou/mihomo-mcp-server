#!/usr/bin/env python3
"""
MCP Node Manager — 一键部署脚本
===============================
自动检测/下载/安装/配置 Mihomo 内核，然后启动 MCP 服务。

用法:
  python3 install.py              # 完整部署（安装Mihomo + 启动MCP）
  python3 install.py --mcp-only   # 仅启动MCP（假设Mihomo已就绪）
  python3 install.py --dry-run    # 仅检测，不做实际操作
"""

import os, sys, subprocess, json, urllib.request, urllib.error
import shutil, stat, time, tempfile, re, textwrap

# ─── 路径配置 ──────────────────────────────────────

MIHOMO_BIN = "/usr/local/bin/mihomo"
MIHOMO_BACKUP = "/usr/local/bin/mihomo.bak"
MIHOMO_CONFIG_DIR = "/etc/mihomo"
MIHOMO_CONFIG = "/etc/mihomo/config.yaml"
MIHOMO_SERVICE = "/etc/systemd/system/mihomo.service"
GITHUB_REPO = "MetaCubeX/mihomo"

MCP_DIR = os.path.dirname(os.path.abspath(__file__))
MCP_PORT = 9010
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# ─── 颜色工具 ──────────────────────────────────────

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def ok(msg):    print(f"  {GREEN}✅{RESET} {msg}")
def warn(msg):  print(f"  {YELLOW}⚠{RESET} {msg}")
def fail(msg):  print(f"  {RED}❌{RESET} {msg}")
def info(msg):  print(f"  {CYAN}ℹ{RESET} {msg}")
def step(n, total, msg):
    print(f"\n{BOLD}[{n}/{total}]{RESET} {msg}")


# ─── 工具函数 ──────────────────────────────────────

def run(cmd, timeout=30, check=False) -> subprocess.CompletedProcess:
    """运行命令并返回结果."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, 124, "", f"超时({timeout}s)"
        )


def sudo_run(cmd, timeout=30) -> subprocess.CompletedProcess:
    """用 sudo 运行命令."""
    return run(["sudo"] + cmd, timeout=timeout)


def github_api(path: str) -> dict | list | None:
    """调用 GitHub API."""
    url = f"https://api.github.com/{path}"
    headers = {
        "User-Agent": "mcp-nodes-installer",
        "Accept": "application/vnd.github.v3+json",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def detect_arch() -> str:
    """检测 CPU 架构 (v3 = 带 AVX2, v1 = 通用)."""
    try:
        with open("/proc/cpuinfo") as f:
            cpuinfo = f.read()
        return "v3" if "avx2" in cpuinfo else "v1"
    except Exception:
        return "v1"


def get_current_version() -> str | None:
    """获取已安装的 Mihomo 版本."""
    if not os.path.exists(MIHOMO_BIN):
        return None
    r = run([MIHOMO_BIN, "-v"], timeout=5)
    if r.returncode != 0:
        return None
    text = r.stderr.strip() or r.stdout.strip()
    m = re.search(r'v?(\d+\.\d+\.\d+)', text)
    return m.group(0) if m else None


def find_asset(release: dict, arch: str) -> dict | None:
    """在 release 中找对应 amd64 资产."""
    tag = release.get("tag_name", "")
    # 优先精确匹配
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if "linux" in name and "amd64" in name:
            if arch == "v3" and "v3" in name:
                return asset
            if arch == "v1" and "v3" not in name:
                return asset
    # 降级: 任意 linux-amd64
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if "linux" in name and "amd64" in name:
            return asset
    return None


def get_latest_release() -> dict | None:
    """获取最新 release."""
    return github_api(f"repos/{GITHUB_REPO}/releases/latest")


# ═══════════════════════════════════════════════════
# 部署步骤
# ═══════════════════════════════════════════════════

TOTAL_STEPS = 7


def step1_check_mihomo() -> dict:
    """Step 1: 检测 Mihomo 安装状态."""
    step(1, TOTAL_STEPS, "检测 Mihomo 安装状态")

    installed = os.path.exists(MIHOMO_BIN)
    version = get_current_version()
    service_exists = os.path.exists(MIHOMO_SERVICE)
    service_active = False

    if service_exists:
        r = sudo_run(["systemctl", "is-active", "mihomo"])
        service_active = r.stdout.strip() == "active"

    config_exists = os.path.exists(MIHOMO_CONFIG)

    info(f"二进制: {MIHOMO_BIN}")
    info(f"版本:    {version or '未安装'}")
    info(f"服务:    {'存在' if service_exists else '不存在'} "
          f"{'(运行中)' if service_active else '(未运行)'}" if service_exists else "")
    info(f"配置:    {'存在' if config_exists else '不存在'}")

    return {
        "installed": installed,
        "version": version,
        "service_exists": service_exists,
        "service_active": service_active,
        "config_exists": config_exists,
    }


def step2_download_kernel(arch: str, force: bool = False) -> str | None:
    """Step 2: 下载最新内核."""
    step(2, TOTAL_STEPS, "获取最新 Mihomo 内核")

    print(f"  架构: {arch}")

    release = get_latest_release()
    if not release or (isinstance(release, dict) and "_mcp_error" in release):
        fail("无法从 GitHub 获取最新 release")
        return None

    tag = release.get("tag_name", "?")
    info(f"最新版本: {tag}")

    asset = find_asset(release, arch)
    if not asset:
        fail(f"未找到 Linux amd64 ({arch}) 构建")
        return None

    url = asset["browser_download_url"]
    name = asset["name"]
    size_mb = round(asset["size"] / 1024 / 1024, 1)
    info(f"目标文件: {name} ({size_mb}MB)")

    print(f"  ↓ 下载中...", end="", flush=True)
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "mcp-nodes-installer"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        print(f" {len(data)/1024/1024:.1f}MB 完成")
    except Exception as e:
        print()
        fail(f"下载失败: {e}")
        return None

    # 写入临时文件
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(data)
    tmp.close()
    os.chmod(tmp.name, 0o755)

    ok(f"下载完成: {name}")
    return tmp.name


def step3_install_binary(tmp_path: str) -> bool:
    """Step 3: 安装二进制到系统."""
    step(3, TOTAL_STEPS, "安装二进制")

    # 备份旧版本
    if os.path.exists(MIHOMO_BIN):
        info("备份当前版本...")
        r = sudo_run(["cp", MIHOMO_BIN, MIHOMO_BACKUP])
        if r.returncode != 0:
            warn(f"备份失败: {r.stderr.strip()}")
        else:
            ok("已备份到 " + MIHOMO_BACKUP)

    # 安装新版本
    info("安装新版本...")
    r = sudo_run(["cp", tmp_path, MIHOMO_BIN])
    if r.returncode != 0:
        fail(f"安装失败: {r.stderr.strip()}")
        os.unlink(tmp_path)
        return False

    # 设置权限
    sudo_run(["chmod", "755", MIHOMO_BIN])
    os.unlink(tmp_path)

    # 验证
    ver = get_current_version()
    if ver:
        ok(f"安装成功: {MIHOMO_BIN} ({ver})")
        return True
    else:
        fail("安装后验证失败")
        return False


def step4_create_config() -> bool:
    """Step 4: 创建基础配置文件."""
    step(4, TOTAL_STEPS, "创建配置文件")

    if os.path.exists(MIHOMO_CONFIG):
        info("配置文件已存在，跳过")
        return True

    # 确保目录存在
    sudo_run(["mkdir", "-p", MIHOMO_CONFIG_DIR])

    config_yaml = textwrap.dedent(f"""\
    # MCP Node Manager — 自动部署基础配置
    # 可根据需要自行修改

    port: 7890
    socks-port: 7891
    mixed-port: 7890
    external-controller: 0.0.0.0:9090
    allow-lan: true
    mode: rule
    log-level: info
    ipv6: true

    # DNS 配置（fake-ip 模式）
    dns:
      enable: true
      listen: 0.0.0.0:53
      ipv6: true
      default-nameserver:
        - 114.114.114.114
        - 223.5.5.5
      nameserver:
        - https://doh.pub/dns-query
        - https://dns.alidns.com/dns-query
      fallback:
        - https://dns.google/dns-query
        - https://cloudflare-dns.com/dns-query
      fallback-filter:
        geoip: true
        ipcidr:
          - 240.0.0.0/4
      fake-ip-range: 198.18.0.1/16
      fake-ip-filter:
        - "+.lan"
        - "+.local"
        - "+.msftconnecttest.com"
        - "+.msftncsi.com"

    # 代理（空 — 请用 MCP 工具添加订阅）
    proxies: []

    # 代理组
    proxy-groups:
      - name: GLOBAL
        type: Select
        proxies:
          - DIRECT
          - REJECT
          - 🚀 自动选择
          - 🎯 手动选择
          - 🌐 国外流量
      - name: 🚀 自动选择
        type: url-test
        proxies:
          - DIRECT
        url: https://www.gstatic.com/generate_204
        interval: 300
        tolerance: 50
      - name: 🎯 手动选择
        type: Select
        proxies:
          - DIRECT
      - name: 🌐 国外流量
        type: Select
        proxies:
          - 🚀 自动选择
          - 🎯 手动选择
          - DIRECT

    # 规则（基础版，可自行扩展）
    rules:
      - GEOIP,PRIVATE,DIRECT
      - GEOIP,CN,DIRECT
      - MATCH,🌐 国外流量

    # 订阅占位（用 MCP 添加: add_subscription）
    proxy-providers: {{}}
    """)

    # 写入临时文件后用 sudo 复制
    tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".yaml")
    tmp.write(config_yaml)
    tmp.close()

    r = sudo_run(["cp", tmp.name, MIHOMO_CONFIG])
    os.unlink(tmp.name)
    if r.returncode != 0:
        fail(f"写入配置失败: {r.stderr.strip()}")
        return False

    ok(f"已创建基础配置: {MIHOMO_CONFIG}")
    return True


def step5_create_service() -> bool:
    """Step 5: 创建 systemd 服务."""
    step(5, TOTAL_STEPS, "创建 systemd 服务")

    if os.path.exists(MIHOMO_SERVICE):
        info("服务文件已存在，跳过")
        return True

    service = textwrap.dedent(f"""\
    [Unit]
    Description=Mihomo Proxy Service (MCP Managed)
    After=network.target network-online.target
    Wants=network-online.target

    [Service]
    Type=simple
    User=root
    ExecStart={MIHOMO_BIN} -d {MIHOMO_CONFIG_DIR}
    Restart=on-failure
    RestartSec=5
    LimitNOFILE=1000000

    [Install]
    WantedBy=multi-user.target
    """)

    tmp = tempfile.NamedTemporaryFile(mode="w", delete=False)
    tmp.write(service)
    tmp.close()

    r = sudo_run(["cp", tmp.name, MIHOMO_SERVICE])
    os.unlink(tmp.name)
    if r.returncode != 0:
        fail(f"创建服务文件失败: {r.stderr.strip()}")
        return False

    # 重载 systemd
    sudo_run(["systemctl", "daemon-reload"])
    sudo_run(["systemctl", "enable", "mihomo"])

    ok(f"已创建服务并启用开机自启: {MIHOMO_SERVICE}")
    return True


def step6_start_service() -> bool:
    """Step 6: 启动 Mihomo 服务并验证."""
    step(6, TOTAL_STEPS, "启动 Mihomo 服务")

    r = sudo_run(["systemctl", "restart", "mihomo"])
    if r.returncode != 0:
        fail(f"启动失败: {r.stderr.strip()}")
        info("查看日志: sudo journalctl -u mihomo -n 30 --no-pager")
        return False

    # 等待就绪
    print("  ⏳ 等待服务就绪...", end="", flush=True)
    for i in range(15):
        time.sleep(1)
        # 检查 systemd 状态
        r2 = sudo_run(["systemctl", "is-active", "mihomo"])
        if r2.stdout.strip() == "active":
            # 再检查 API
            try:
                resp = urllib.request.urlopen(
                    "http://127.0.0.1:9090/version", timeout=3
                )
                ver = json.loads(resp.read()) if resp.status == 200 else {}
                print()
                ok(f"Mihomo 已启动并运行 (v{ver.get('version', '?')})")
                return True
            except Exception:
                print(".", end="", flush=True)
        else:
            print(".", end="", flush=True)
    print()

    # 检查日志
    r3 = sudo_run(["journalctl", "-u", "mihomo", "-n", "15", "--no-pager"])
    fail("服务超时未就绪")
    info(f"最后日志:\n{r3.stdout[:500] if r3.stdout else '无日志'}")
    return False


def step7_setup_mcp() -> bool:
    """Step 7: 确保 MCP 依赖就绪并启动."""
    step(7, TOTAL_STEPS, "启动 MCP 节点管理器")

    # 检查依赖
    info("检查 Python 依赖...")
    r = run([sys.executable, "-c", "import yaml"], check=False)
    if r.returncode != 0:
        info("安装 PyYAML...")
        r2 = run([sys.executable, "-mpip", "install", "pyyaml"], timeout=60)
        if r2.returncode != 0:
            warn("PyYAML 安装失败，部分功能可能受限")
        else:
            ok("PyYAML 已安装")

    # 检查是否有旧 screen 会话
    r = run(["screen", "-ls"])
    if "mcp_nodes" in r.stdout:
        warn("检测到已有的 mcp_nodes 会话，将重启")
        run(["screen", "-S", "mcp_nodes", "-X", "quit"])

    # 启动
    info("启动 MCP 服务器...")
    r = run([
        "screen", "-dmS", "mcp_nodes",
        "/bin/bash", "-c",
        f"cd {MCP_DIR} && exec {sys.executable} main.py"
    ])
    if r.returncode != 0:
        fail(f"启动 MCP 失败: {r.stderr.strip()}")
        return False

    time.sleep(2)

    # 验证
    try:
        resp = urllib.request.urlopen(
            f"http://127.0.0.1:{MCP_PORT}/health", timeout=5
        )
        data = json.loads(resp.read())
        tools = data.get("tools", 0)
        ok(f"MCP 节点管理器已启动 (端口 {MCP_PORT}, {tools} 个工具)")
        return True
    except Exception:
        warn(f"MCP 可能尚未就绪，请稍后检查: curl http://127.0.0.1:{MCP_PORT}/health")
        return False


# ═══════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════

def print_banner():
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════╗
║   MCP Node Manager — 一键部署     ║
║   v2.2 • Mihomo + MCP 自动安装    ║
╚══════════════════════════════════════╝{RESET}
""")


def main():
    dry_run = "--dry-run" in sys.argv
    mcp_only = "--mcp-only" in sys.argv

    print_banner()

    if dry_run:
        info("🔍 仅检测模式（--dry-run）\n")
        status = step1_check_mihomo()
        print()

        if status["installed"]:
            ok(f"Mihomo {status['version']} 已安装")
        else:
            warn("Mihomo 未安装")
        if status["service_active"]:
            ok("服务运行中")
        else:
            warn("服务未运行")
        if status["config_exists"]:
            ok("配置文件存在")
        else:
            warn("配置文件不存在")

        print(f"\n  {CYAN}建议: 直接运行 python3 install.py 完成部署{RESET}")
        return

    if mcp_only:
        info("🔄 MCP 仅启动模式\n")
        success = step7_setup_mcp()
        print()
        if success:
            ok("完成！")
        else:
            fail("MCP 启动遇到问题")
        return

    # ─── 完整流程 ───

    # Step 1: 检测
    status = step1_check_mihomo()

    if status["installed"] and status["service_active"] and status["config_exists"]:
        print(f"\n  {GREEN}Mihomo 已就绪 (v{status['version']}){RESET}")
        print(f"  → 跳过步骤 2-6，直接启动 MCP")
        print()
        step7_setup_mcp()
        print(f"\n{GREEN}{BOLD}🎉 部署完成！{RESET}")
        return

    # Step 2-3: 下载 + 安装内核
    if not status["installed"]:
        arch = detect_arch()
        tmp = step2_download_kernel(arch)
        if not tmp:
            fail("下载失败，无法继续")
            return 1
        if not step3_install_binary(tmp):
            return 1
    else:
        info(f"Mihomo 已安装 (v{status['version']})，跳过下载")

    # Step 4: 创建配置
    if not step4_create_config():
        return 1

    # Step 5: 创建服务
    if not step5_create_service():
        return 1

    # Step 6: 启动
    if not step6_start_service():
        return 1

    # Step 7: MCP
    print()
    step7_setup_mcp()

    print(f"\n{GREEN}{BOLD}🎉 部署完成！{RESET}")
    print(f"""
  {CYAN}MCP 服务:  http://127.0.0.1:{MCP_PORT}/mcp/sse
  健康检查:  http://127.0.0.1:{MCP_PORT}/health
  Mihomo API: http://127.0.0.1:9090
  代理端口:  7890 (mixed-port)
  管理面板:  http://127.0.0.1:9091 (MetaCubeXD){RESET}
""")


if __name__ == "__main__":
    sys.exit(main() or 0)
