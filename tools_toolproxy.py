"""
工具代理管理：独立于系统代理的第二个 Mihomo 实例。
专用端口 7893，API 端口 9092，与服务完全隔离。
空闲 5 分钟自动停止。
"""

import os, subprocess, time, json, urllib.request, urllib.parse
import shutil, tempfile, threading

from config import R, GITHUB_TOKEN

TOOL_PORT = 7893
TOOL_API_PORT = 9092
TOOL_API = f"http://127.0.0.1:{TOOL_API_PORT}"
TOOL_CONFIG_DIR = "/etc/mihomo-tool"
TOOL_CONFIG = f"{TOOL_CONFIG_DIR}/config.yaml"
TOOL_SERVICE = "/etc/systemd/system/mihomo-tool.service"
TOOL_BIN = "/usr/local/bin/mihomo"
TOOL_SUB_FILE = f"{TOOL_CONFIG_DIR}/sub.yaml"
IDLE_TIMEOUT = 300  # 5 分钟空闲自动关闭

# 订阅配置源（从系统 Mihomo 的 proxy-providers 获取）
SYSTEM_CONFIG = "/etc/mihomo/config.yaml"


def _read_system_config() -> dict | None:
    """读取系统 Mihomo 配置。"""
    try:
        import yaml
        with open(SYSTEM_CONFIG) as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def _ensure_dir():
    """确保配置目录存在。"""
    subprocess.run(["sudo", "mkdir", "-p", TOOL_CONFIG_DIR],
                   capture_output=True, timeout=10)


# 空闲自动停止
_idle_timer: threading.Timer | None = None
_idle_lock = threading.Lock()


def _cancel_idle_timer():
    global _idle_timer
    with _idle_lock:
        if _idle_timer is not None:
            _idle_timer.cancel()
            _idle_timer = None


def _reset_idle_timer():
    """重置空闲计时器。每次有活动时调用。"""
    with _idle_lock:
        global _idle_timer
        if _idle_timer is not None:
            _idle_timer.cancel()
        _idle_timer = threading.Timer(IDLE_TIMEOUT, _idle_stop)
        _idle_timer.daemon = True
        _idle_timer.start()


def _idle_stop():
    """空闲超时后自动停止工具代理。"""
    try:
        subprocess.run(
            ["sudo", "pkill", "-f", "mihomo.*mihomo-tool"],
            capture_output=True, timeout=10
        )
    except Exception:
        pass


def _ensure_running() -> bool:
    """确保工具代理在运行，不在则自动启动。返回是否成功。"""
    try:
        r = subprocess.run(["pgrep", "-f", "mihomo.*mihomo-tool"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return True
    except Exception:
        pass

    if not os.path.exists(TOOL_CONFIG):
        return False

    try:
        subprocess.Popen(
            ["sudo", TOOL_BIN, "-d", TOOL_CONFIG_DIR],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(10):
            time.sleep(1)
            try:
                req = urllib.request.Request(
                    f"{TOOL_API}/version",
                    headers={"User-Agent": "mcp-nodes/2.1"})
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def tool_toolproxy_status(**kwargs) -> dict:
    """查看工具代理状态。"""
    import yaml

    running = False
    pid = None
    try:
        r = subprocess.run(["pgrep", "-f", f"mihomo.*mihomo-tool"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            running = True
            pid = r.stdout.strip().split("\n")[0]
    except Exception:
        pass

    api_ok = False
    try:
        req = urllib.request.Request(f"{TOOL_API}/version",
                                     headers={"User-Agent": "mcp-nodes/2.1"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            api_ok = resp.status == 200
    except Exception:
        pass

    config_ok = os.path.exists(TOOL_CONFIG)

    return R.ok(data={
        "running": running,
        "pid": pid,
        "api_reachable": api_ok,
        "config_exists": config_ok,
        "port": TOOL_PORT,
        "api_port": TOOL_API_PORT,
    }, message=f"工具代理: {'✅ 运行中' if running else '⛔ 未启动'} "
               f"端口 {TOOL_PORT} API {TOOL_API_PORT}")


def tool_toolproxy_init(**kwargs) -> dict:
    """初始化工具代理配置（从系统 Mihomo 复制订阅和基础配置）。"""
    import yaml

    _ensure_dir()

    sys_cfg = _read_system_config()
    if sys_cfg is None:
        return R.fail("CONFIG_ERROR", "无法读取系统 Mihomo 配置")

    # 提取订阅信息
    providers = sys_cfg.get("proxy-providers", {})
    if not providers:
        return R.fail("CONFIG_ERROR", "系统 Mihomo 没有配置订阅")

    # 构建工具代理配置
    tool_cfg = {
        "mixed-port": TOOL_PORT,
        "external-controller": f"127.0.0.1:{TOOL_API_PORT}",
        "allow-lan": False,
        "mode": "rule",
        "log-level": "silent",
        "ipv6": False,
        "proxy-providers": providers,
        "proxies": [],
        "proxy-groups": [
            {
                "name": "TOOL-PROXY",
                "type": "select",
                "proxies": ["DIRECT"],
                "use": list(providers.keys()) if providers else [],
            }
        ],
        "rules": [
            "MATCH,TOOL-PROXY",
        ],
    }

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                         delete=False) as tmp:
            yaml.dump(tool_cfg, tmp, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)
            tmp_path = tmp.name

        subprocess.run(["sudo", "cp", tmp_path, TOOL_CONFIG],
                       capture_output=True, timeout=10)
        os.unlink(tmp_path)
    except Exception as e:
        return R.config_error(f"写入配置失败: {e}")

    return R.ok(data={"config": TOOL_CONFIG, "port": TOOL_PORT},
                 message=f"✅ 工具代理配置已创建（端口 {TOOL_PORT}）")


def tool_toolproxy_start(**kwargs) -> dict:
    """启动工具代理。"""
    if not os.path.exists(TOOL_CONFIG):
        return R.fail("CONFIG_ERROR",
                       "工具代理配置不存在，请先执行 toolproxy_init",
                       suggestions=["先运行 toolproxy_init 创建配置"])

    try:
        r = subprocess.run(["pgrep", "-f", f"mihomo.*mihomo-tool"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return R.ok(message="工具代理已经在运行中")
    except Exception:
        pass

    try:
        subprocess.Popen(
            ["sudo", TOOL_BIN, "-d", TOOL_CONFIG_DIR],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(10):
            time.sleep(1)
            try:
                req = urllib.request.Request(f"{TOOL_API}/version",
                                             headers={"User-Agent": "mcp-nodes/2.1"})
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status == 200:
                        return R.ok(
                            data={"port": TOOL_PORT},
                            message=f"✅ 工具代理已启动（端口 {TOOL_PORT}）")
            except Exception:
                continue
        return R.fail("TIMEOUT", "工具代理启动超时")
    except Exception as e:
        return R.fail("START_FAILED", f"启动失败: {e}")


def tool_toolproxy_stop(**kwargs) -> dict:
    """停止工具代理。"""
    _cancel_idle_timer()
    try:
        r = subprocess.run(
            ["sudo", "pkill", "-f", f"mihomo.*mihomo-tool"],
            capture_output=True, timeout=10
        )
        if r.returncode == 0:
            return R.ok(message="⏹ 工具代理已停止")
        return R.ok(message="工具代理未在运行")
    except Exception as e:
        return R.fail("STOP_FAILED", f"停止失败: {e}")


def tool_toolproxy_switch_node(**kwargs) -> dict:
    """切换工具代理的节点（不影响系统代理）。"""
    node = kwargs.get("node", "")
    if not node:
        return R.invalid_param("node", "节点名称不能为空")

    try:
        encoded = urllib.parse.quote("TOOL-PROXY", safe="")
        req = urllib.request.Request(
            f"{TOOL_API}/proxies/{encoded}",
            data=json.dumps({"name": node}).encode(),
            method="PUT",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 204:
                _reset_idle_timer()
                return R.ok(
                    data={"node": node, "group": "TOOL-PROXY"},
                    message=f"✅ 工具代理已切换: TOOL-PROXY → {node}")
        return R.fail("SWITCH_FAILED", f"切换失败: {node}")
    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode(errors="replace")
        return R.fail("SWITCH_FAILED",
                       f"切换失败: HTTP {e.code}",
                       details=body)
    except Exception as e:
        return R.fail("SWITCH_ERROR", f"切换异常: {e}")
def tool_toolproxy_run_with_node(**kwargs) -> dict:
    """在工具代理指定节点下执行命令，不影响系统代理。
    自动启动工具代理，执行完后 5 分钟无活动自动关闭。
    """
    import subprocess, os, shlex

    command = kwargs.get("command", "")
    node = kwargs.get("node", "")
    timeout = kwargs.get("timeout", 30)

    if not command:
        return R.invalid_param("command", "命令不能为空")
    if not node:
        return R.invalid_param("node", "节点名称不能为空")

    # 自动启动（如果没在运行）
    if not _ensure_running():
        return R.fail("START_FAILED", "无法启动工具代理",
                       suggestions=["先执行 toolproxy_init 初始化配置"])

    # 先切节点
    sw_result = tool_toolproxy_switch_node(node=node)
    if not sw_result.get("success"):
        return sw_result

    time.sleep(1)

    # 执行命令（用工具代理端口）
    cmd_start = time.time()
    env = os.environ.copy()
    env["HTTP_PROXY"] = f"http://127.0.0.1:{TOOL_PORT}"
    env["HTTPS_PROXY"] = f"http://127.0.0.1:{TOOL_PORT}"
    try:
        result = subprocess.run(command, shell=True,
            capture_output=True, text=True, timeout=timeout, env=env)
        cmd_duration = time.time() - cmd_start
        stdout = (result.stdout or "")[:5000]
        stderr = (result.stderr or "")[:1000]
        exit_code = result.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr = "", f"超时({timeout}s)"
        exit_code, cmd_duration = -1, timeout
    except Exception as e:
        stdout, stderr = "", f"异常: {e}"
        exit_code, cmd_duration = -2, time.time() - cmd_start

    # 重置空闲计时器
    _reset_idle_timer()

    total = time.time() - cmd_start + 1
    return R.ok(
        data={
            "node": node, "command": command, "exit_code": exit_code,
            "stdout": stdout, "stderr": stderr,
            "proxy_port": TOOL_PORT,
            "idle_timeout_s": IDLE_TIMEOUT,
            "cmd_time_s": round(cmd_duration, 2),
            "total_time_s": round(total, 2),
        },
        message=f"通过工具代理 '{node}' 完成(退出码 {exit_code}, {round(cmd_duration, 1)}s)"
                f"，{IDLE_TIMEOUT // 60} 分钟无活动自动关闭"
    )


def tool_toolproxy_list_nodes(**kwargs) -> dict:
    """列出工具代理中的可用节点。"""
    try:
        req = urllib.request.Request(
            f"{TOOL_API}/proxies",
            headers={"User-Agent": "mcp-nodes/2.1"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return R.fail("API_ERROR", f"无法连接工具代理: {e}",
                       suggestions=["先启动工具代理: toolproxy_start"])

    proxies = data.get("proxies", {})
    group = proxies.get("TOOL-PROXY", {})
    all_nodes = group.get("all", [])
    now = group.get("now", "")

    return R.ok(data={
        "current": now,
        "nodes": all_nodes,
        "total": len(all_nodes),
    }, message=f"工具代理当前节点: {now}，共 {len(all_nodes)} 个节点可用")
