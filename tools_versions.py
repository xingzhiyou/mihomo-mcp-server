"""
服务控制与内核版本管理工具。
包含 Mihomo 启停/状态查看、版本升级/回滚。
"""

import os, subprocess, re, time, json, urllib.request

from config import R, MIHOMO_API, GITHUB_TOKEN
from config_manager import run_systemctl, restart_mihomo

MIHOMO_BIN = "/usr/local/bin/mihomo"
MIHOMO_BACKUP = "/usr/local/bin/mihomo.bak"
GITHUB_REPO = "MetaCubeX/mihomo"


# ─── 服务控制 ──────────────────────────────────────


def tool_mihomo_status(**kwargs) -> dict:
    """查看 Mihomo 服务状态。"""
    result = run_systemctl("status")
    if result.get("success"):
        data = result.get("data", {})
        active = data.get("active", False)
        stdout = data.get("stdout", "")

        # 额外信息
        try:
            groups_resp = urllib.request.urlopen(
                f"{MIHOMO_API}/groups", timeout=5
            )
            groups = json.loads(groups_resp.read())
            group_count = len(groups.get("proxy_groups", {}))
            data["api_reachable"] = True
            data["group_count"] = group_count
        except Exception:
            data["api_reachable"] = False
            data["group_count"] = 0

        # 版本信息
        ver = _get_current_version()
        data["version"] = ver

        return R.ok(
            data=data,
            message=f"Mihomo {'✅ 运行中' if active else '⛔ 已停止'}"
                    + (f" v{ver['version']}" if ver else "")
        )

    return result


def tool_mihomo_start(**kwargs) -> dict:
    """启动 Mihomo 服务。"""
    return run_systemctl("start")


def tool_mihomo_stop(**kwargs) -> dict:
    """停止 Mihomo 服务。"""
    return run_systemctl("stop")


# ─── 内核版本管理 ──────────────────────────────────


def _detect_mihomo_arch() -> str:
    """检测当前 CPU 适合的 mihomo 构建版本。"""
    try:
        with open("/proc/cpuinfo") as f:
            cpuinfo = f.read()
        avx2 = "avx2" in cpuinfo
        return "v3" if avx2 else "v1"
    except Exception:
        return "v1"


def _get_current_version() -> dict | None:
    """获取当前安装的 Mihomo 版本。"""
    try:
        result = subprocess.run(
            [MIHOMO_BIN, "-v"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            full = result.stderr.strip() or result.stdout.strip()
            m = re.search(r'v?(\d+\.\d+\.\d+)', full)
            if m:
                return {
                    "version": m.group(1),
                    "tag": f"v{m.group(1)}",
                    "full_string": full,
                    "binary_path": MIHOMO_BIN,
                    "binary_size_bytes": os.path.getsize(MIHOMO_BIN),
                    "binary_size_mb": round(
                        os.path.getsize(MIHOMO_BIN) / 1024 / 1024, 1
                    )
                }
            return {"version": "unknown", "full_string": full}
        return None
    except Exception:
        return None


def _github_api_get(path: str, timeout: int = 15) -> dict | list | None:
    """访问 GitHub API（使用 Token 避免限流）。"""
    url = f"https://api.github.com/{path}"
    headers = {
        "User-Agent": "mcp-nodes/2.1",
        "Accept": "application/vnd.github.v3+json",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        if e.code == 403:
            return {"_mcp_error": R.fail(
                "GITHUB_RATE_LIMITED",
                "GitHub API 请求超限",
                details=f"403: {body}",
                suggestions=["等待限流重置（~1小时）",
                             "配置 GITHUB_TOKEN 环境变量提高限额"],
                affected=["github.com"]
            )}
        return {"_mcp_error": R.fail(
            "GITHUB_API_ERROR",
            f"GitHub API HTTP {e.code}",
            details=body
        )}
    except urllib.error.URLError as e:
        return {"_mcp_error": R.fail(
            "GITHUB_NETWORK_ERROR",
            f"GitHub 网络不可达: {e.reason}",
            suggestions=["检查代理是否正常工作",
                         "尝试切换节点后再试"],
            affected=["github.com"]
        )}


def _get_latest_release() -> dict | None | dict:
    """获取最新 release。"""
    result = _github_api_get(
        f"repos/{GITHUB_REPO}/releases/latest"
    )
    if isinstance(result, dict) and "_mcp_error" in result:
        return result
    return result


def _get_releases(per_page: int = 20) -> list | dict:
    """获取 release 列表。"""
    result = _github_api_get(
        f"repos/{GITHUB_REPO}/releases?per_page={per_page}"
    )
    return result or []


def _find_asset(release: dict, arch: str) -> dict | None:
    """在 release 中找对应架构的 amd64 资产。"""
    tag = release.get("tag_name", "")
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if "linux" in name and "amd64" in name:
            if arch == "v3" and "v3" in name:
                return asset
            if arch == "v1" and "v3" not in name:
                return asset
    # 降级兼容
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if "linux" in name and "amd64" in name:
            return asset
    return None


def _download_and_install(url: str, version_tag: str) -> tuple[bool, str]:
    """下载并安装 Mihomo 二进制。"""
    try:
        # 备份当前二进制
        if os.path.exists(MIHOMO_BIN):
            subprocess.run(
                ["sudo", "cp", MIHOMO_BIN, MIHOMO_BACKUP],
                capture_output=True, timeout=10
            )

        # 下载
        req = urllib.request.Request(
            url, headers={"User-Agent": "mcp-nodes/2.1"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()

        # 写入临时文件
        tmp_path = "/tmp/mihomo_new"
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.chmod(tmp_path, 0o755)

        # 用 sudo 替换
        result = subprocess.run(
            ["sudo", "cp", tmp_path, MIHOMO_BIN],
            capture_output=True, text=True, timeout=10
        )
        os.unlink(tmp_path)

        if result.returncode != 0:
            return False, f"sudo cp 失败: {result.stderr.strip()}"

        # 验证
        ver = _get_current_version()
        if not ver:
            return False, "新二进制无法运行"

        # 重启
        ok, msg = restart_mihomo()
        if ok:
            return True, f"已升级至 {version_tag} 并重启"
        else:
            return False, f"已安装但重启失败: {msg}"

    except Exception as e:
        return False, str(e)


def tool_mihomo_version(**kwargs) -> dict:
    """查看当前安装的 Mihomo 版本详细信息。"""
    ver = _get_current_version()
    if not ver:
        return R.fail(
            "VERSION_NOT_FOUND",
            "无法获取 Mihomo 版本信息",
            details=f"{MIHOMO_BIN} 可能不存在或无法执行",
            suggestions=["检查 Mihomo 是否已安装",
                         f"运行: {MIHOMO_BIN} -v"]
        )

    arch = _detect_mihomo_arch()

    # 获取远程最新版本信息
    latest = _get_latest_release()
    if isinstance(latest, dict) and "_mcp_error" not in latest:
        ver["latest_version"] = latest.get("tag_name", "?")
        ver["has_update"] = (
            ver.get("tag") != latest.get("tag_name")
        ) if ver.get("tag") else False
    else:
        ver["latest_version"] = "?"
        ver["has_update"] = False

    ver["arch_detected"] = arch

    return R.ok(
        data=ver,
        message=f"Mihomo v{ver['version']}"
                + (f"（⬆ 最新 {ver['latest_version']}）"
                   if ver.get("has_update") else " ✅ 已是最新")
    )


def tool_mihomo_list_versions(**kwargs) -> dict:
    """列出所有可用版本。"""
    arch = _detect_mihomo_arch()
    current = _get_current_version()
    current_tag = current["tag"] if current else ""

    releases = _get_releases(per_page=30)
    if isinstance(releases, dict) and "_mcp_error" in releases:
        return releases["_mcp_error"]

    versions = []
    for r in releases:
        tag = r.get("tag_name", "")
        asset = _find_asset(r, arch)
        versions.append({
            "tag": tag,
            "published": r.get("published_at", "")
                           .replace("T", " ").replace("Z", ""),
            "prerelease": r.get("prerelease", False),
            "is_current": tag == current_tag,
            "asset_url": (asset["browser_download_url"]
                          if asset else None),
            "asset_name": asset["name"] if asset else None,
            "size_mb": (round(asset["size"] / 1024 / 1024, 1)
                        if asset else None)
        })

    return R.ok(
        data={
            "versions": versions,
            "total": len(versions),
            "arch_detected": arch,
            "current_version": current_tag
        },
        message=f"共 {len(versions)} 个版本（{arch}）"
    )


def tool_mihomo_upgrade(**kwargs) -> dict:
    """升级或降级 Mihomo 内核到指定版本。"""
    version = kwargs.get("version", "latest")

    # 获取目标版本
    if version == "latest":
        latest = _get_latest_release()
        if isinstance(latest, dict) and "_mcp_error" in latest:
            return latest["_mcp_error"]
        if latest is None:
            return R.fail(
                "GITHUB_ERROR", "无法获取最新版本信息",
                suggestions=["检查网络连接",
                             "检查 GITHUB_TOKEN 是否有效"]
            )
        target = latest
        version_tag = target["tag_name"]
    else:
        releases = _get_releases(per_page=30)
        if isinstance(releases, dict) and "_mcp_error" in releases:
            return releases["_mcp_error"]
        target = None
        for r in releases:
            if r["tag_name"] == version or r["tag_name"] == f"v{version}":
                target = r
                version_tag = r["tag_name"]
                break
        if not target:
            return R.not_found(
                "version", version,
                [r["tag_name"] for r in releases[:10]]
            )

    # 检查是否已是最新
    current = _get_current_version()
    if current and current.get("tag") == version_tag:
        if kwargs.get("force"):
            pass  # 强制重装
        else:
            return R.ok(
                data={"version": version_tag, "already_current": True},
                message=f"已经是 v{current['version']}，无需升级"
                        "（加 force=true 强制重装）"
            )

    # 找资产
    arch = _detect_mihomo_arch()
    asset = _find_asset(target, arch)
    if not asset:
        return R.fail(
            code="ASSET_NOT_FOUND",
            message=f"未找到 {version_tag} 的 Linux amd64 构建",
            details=f"架构: {arch}，"
                    f"资产数: {len(target.get('assets', []))}",
            suggestions=["尝试其他版本",
                         "手动下载: "
                         "https://github.com/MetaCubeX/mihomo/releases"],
            affected=[version_tag]
        )

    url = asset["browser_download_url"]
    ok, msg = _download_and_install(url, version_tag)
    if not ok:
        return R.fail(
            code="UPGRADE_FAILED",
            message=f"升级失败: {msg}",
            suggestions=["检查磁盘空间和网络",
                         "尝试手动下载安装",
                         "回滚: tool_mihomo_rollback"]
        )

    return R.ok(
        data={
            "version": version_tag,
            "arch": arch,
            "file_size_mb": round(asset["size"] / 1024 / 1024, 1),
            "downloaded_from": url
        },
        message=f"✅ Mihomo 已升级至 {version_tag}（{arch}）"
    )


def tool_mihomo_rollback(**kwargs) -> dict:
    """回滚到备份版本。"""
    if not os.path.exists(MIHOMO_BACKUP):
        return R.fail(
            "BACKUP_NOT_FOUND",
            "未找到备份文件",
            details=f"{MIHOMO_BACKUP} 不存在",
            suggestions=["只有执行过升级操作后才有备份",
                         "可重新安装: tool_mihomo_upgrade"]
        )

    try:
        # 停服
        subprocess.run(
            ["sudo", "systemctl", "stop", "mihomo"],
            capture_output=True, timeout=30
        )

        # 替换
        result = subprocess.run(
            ["sudo", "cp", MIHOMO_BACKUP, MIHOMO_BIN],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return R.fail(
                "ROLLBACK_FAILED",
                "回滚失败",
                details=f"sudo cp: {result.stderr.strip()}",
                suggestions=["检查文件权限",
                             f"手动: sudo cp {MIHOMO_BACKUP} {MIHOMO_BIN}"]
            )

        os.chmod(MIHOMO_BIN, 0o755)

        # 验证
        ver = _get_current_version()
        ver_str = f"v{ver['version']}" if ver else "?"

        # 重启
        ok, msg = restart_mihomo()
        if not ok:
            return R.restart_fail(msg)

        return R.ok(
            data={
                "version": ver_str,
                "restored_from": MIHOMO_BACKUP
            },
            message=f"✅ 已回滚至 {ver_str}"
        )

    except Exception as e:
        return R.fail("ROLLBACK_ERROR",
                       f"回滚异常: {e}", details=str(e))
