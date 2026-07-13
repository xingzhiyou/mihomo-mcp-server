"""
订阅管理工具：列出、刷新、添加、修改、删除订阅。
"""

import urllib.request, urllib.parse
import os, time

from config import R, MIHOMO_API, MIHOMO_CONFIG
from mihomo_api import safe_api_get
from config_manager import read_config, write_config, restart_mihomo


def tool_list_subscriptions(**kwargs) -> dict:
    """列出所有订阅的详细信息。"""
    data = safe_api_get("/providers/proxies")
    if "_mcp_error" in data:
        return data["_mcp_error"]

    providers = data.get("providers", {})
    if not providers:
        return R.ok(data={"subscriptions": [], "total": 0},
                    message="没有任何订阅")

    cfg = read_config()
    provider_configs = cfg.get("proxy-providers", {}) if cfg else {}

    subs = []
    for name, info in providers.items():
        vtype = info.get("vehicleType", "?")
        updated = info.get("updatedAt", "?")
        proxies = info.get("proxies", {})
        node_count = (
            len(proxies) if isinstance(proxies, dict)
            else (len(proxies) if isinstance(proxies, list) else 0)
        )

        sub_url = (
            provider_configs.get(name, {}).get("url")
            if name in provider_configs else None
        )

        sub_info = info.get("subscriptionInfo", {})
        traffic = {}
        if sub_info:
            upload = sub_info.get("Upload", 0)
            download = sub_info.get("Download", 0)
            total = sub_info.get("Total", 0)
            expire = sub_info.get("Expire", 0)
            traffic = {
                "upload_gb": round(upload / (1024**3), 1) if upload else 0,
                "download_gb": round(download / (1024**3), 1) if download else 0,
                "used_gb": round((upload + download) / (1024**3), 1),
                "total_gb": round(total / (1024**3), 1) if total else 0,
                "expire_timestamp": expire,
                "expire_date": (
                    time.strftime("%Y-%m-%d", time.localtime(expire))
                    if expire else "N/A"
                )
            }

        subs.append({
            "name": name,
            "type": vtype,
            "node_count": node_count,
            "url": sub_url,
            "updated_at": updated,
            "traffic": traffic
        })

    return R.ok(data={"subscriptions": subs, "total": len(subs)},
                message=f"共 {len(subs)} 个订阅")


def tool_refresh_subscription(**kwargs) -> dict:
    """刷新/更新指定订阅。"""
    name = kwargs.get("name", "sub")
    try:
        encoded = urllib.parse.quote(name, safe='')
        req = urllib.request.Request(
            f"{MIHOMO_API}/providers/proxies/{encoded}",
            method="PUT",
            headers={"User-Agent": "mcp-nodes/2.1"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 204:
                return R.fail("REFRESH_FAILED",
                              f"刷新返回状态 {resp.status}")

        # 获取刷新后的信息
        info = safe_api_get("/providers/proxies")
        if "_mcp_error" not in info:
            providers = info.get("providers", {})
            if name in providers:
                p = providers[name]
                proxies = p.get("proxies", {})
                node_count = (
                    len(proxies) if isinstance(proxies, dict)
                    else (len(proxies) if isinstance(proxies, list) else 0)
                )
                return R.ok(
                    data={
                        "name": name,
                        "node_count": node_count,
                        "updated_at": p.get("updatedAt", "?"),
                        "vehicle_type": p.get("vehicleType", "?")
                    },
                    message=f"订阅 '{name}' 刷新成功（{node_count} 节点）"
                )

        return R.ok(
            data={"name": name},
            message=f"订阅 '{name}' 已刷新"
        )

    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode(errors="replace")
        return R.fail(
            "REFRESH_FAILED",
            f"刷新订阅 '{name}' 失败",
            details=f"HTTP {e.code}: {body}",
            suggestions=["检查订阅名称是否正确",
                         "检查订阅链接是否有效"]
        )
    except Exception as e:
        return R.fail("REFRESH_ERROR",
                       f"刷新异常: {e}", details=str(e))


def tool_add_subscription(**kwargs) -> dict:
    """添加新的订阅。"""
    name = kwargs.get("name", "")
    url = kwargs.get("url", "")
    use_proxy = kwargs.get("use_proxy", True)
    interval = kwargs.get("interval", 3600)

    if not name:
        return R.invalid_param("name", "订阅名称不能为空",
                               example="my-sub")
    if not url:
        return R.invalid_param("url", "订阅链接不能为空",
                               example="https://example.com/sub")

    cfg = read_config()
    if cfg is None:
        return R.config_error("无法读取 config.yaml")

    providers = cfg.get("proxy-providers", {})
    if name in providers:
        return R.already_exists("subscription", name)

    providers[name] = {
        "type": "http",
        "url": url,
        "interval": interval,
        "proxy": use_proxy
    }
    cfg["proxy-providers"] = providers

    ok, err = write_config(cfg)
    if not ok:
        return R.config_error(f"写入失败: {err}")

    ok, msg = restart_mihomo()
    if not ok:
        return R.restart_fail(msg)

    return R.ok(
        data={
            "name": name,
            "url": url,
            "use_proxy": use_proxy,
            "interval": interval
        },
        message=f"订阅 '{name}' 已添加，Mihomo 已重启"
    )


def tool_modify_subscription(**kwargs) -> dict:
    """修改已有订阅的参数。"""
    name = kwargs.get("name", "")
    new_url = kwargs.get("url")
    use_proxy = kwargs.get("use_proxy")
    interval = kwargs.get("interval")
    new_name = kwargs.get("new_name")

    if not name:
        return R.invalid_param("name", "订阅名称不能为空")

    cfg = read_config()
    if cfg is None:
        return R.config_error("无法读取 config.yaml")

    providers = cfg.get("proxy-providers", {})
    if name not in providers:
        return R.not_found("subscription", name, list(providers.keys()))

    changes = []
    if new_url is not None:
        providers[name]["url"] = new_url
        changes.append("url")
    if use_proxy is not None:
        providers[name]["proxy"] = use_proxy
        changes.append("use_proxy")
    if interval is not None and interval > 0:
        providers[name]["interval"] = interval
        changes.append("interval")
    if new_name is not None and new_name != name:
        if new_name in providers:
            return R.already_exists("subscription", new_name)
        providers[new_name] = providers.pop(name)
        changes.append(f"rename: {name} → {new_name}")

    if not changes:
        return R.ok(
            data={"name": name, "no_changes": True},
            message="没有需要修改的字段"
        )

    cfg["proxy-providers"] = providers
    ok, err = write_config(cfg)
    if not ok:
        return R.config_error(f"写入失败: {err}")

    return R.ok(
        data={
            "name": new_name or name,
            "changes": changes
        },
        message=f"订阅 '{name}' 已修改（{len(changes)}项）"
    )


def tool_delete_subscription(**kwargs) -> dict:
    """删除指定订阅。"""
    name = kwargs.get("name", "")
    if not name:
        return R.invalid_param("name", "订阅名称不能为空")

    cfg = read_config()
    if cfg is None:
        return R.config_error("无法读取 config.yaml")

    providers = cfg.get("proxy-providers", {})
    if name not in providers:
        data = safe_api_get("/providers/proxies")
        available = []
        if "_mcp_error" not in data:
            available = list(data.get("providers", {}).keys())
        return R.not_found("subscription", name, available)

    del providers[name]
    cfg["proxy-providers"] = providers

    # 从代理组移除引用
    removed_from = []
    groups = cfg.get("proxy-groups", [])
    for group in groups:
        use_list = group.get("use", [])
        if name in use_list:
            use_list.remove(name)
            removed_from.append(group.get("name", "?"))
            if not use_list:
                group["proxies"] = (
                    group.get("proxies", []) or ["DIRECT"]
                )

    # 删除本地文件
    sub_file = f"{MIHOMO_CONFIG.rsplit('/', 1)[0]}/{name}.yaml"
    file_deleted = os.path.exists(sub_file)
    if file_deleted:
        os.remove(sub_file)

    cfg["proxy-groups"] = groups
    ok, err = write_config(cfg)
    if not ok:
        return R.config_error(f"写入失败: {err}")

    ok, msg = restart_mihomo()
    if not ok:
        return R.restart_fail(msg)

    return R.ok(
        data={
            "name": name,
            "removed_from_groups": removed_from,
            "file_deleted": file_deleted
        },
        message=f"订阅 '{name}' 已删除"
    )
