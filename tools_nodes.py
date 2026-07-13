"""
节点管理工具：代理组查看、节点切换、延迟测试、连通性测试。
"""

import urllib.request, urllib.parse, urllib.error
import json
import time

from config import R, MIHOMO_API, TEST_URL, TEST_TIMEOUT
from mihomo_api import (
    safe_api_get, _api_get, _api_put, get_proxy_groups,
    switch_proxy_node, test_node_delay
)
from config_manager import read_config, write_config, restart_mihomo


def tool_list_groups(**kwargs) -> dict:
    """列出所有代理组及其当前选择的节点。"""
    groups = get_proxy_groups()
    if groups is None or "_mcp_error" in groups:
        return R.api_error("/proxies",
                           "无法获取代理组列表，Mihomo 可能未运行")

    result = []
    for name, info in groups.items():
        now = info.get("now", "N/A")
        all_nodes = info.get("all", [])
        result.append({
            "name": name,
            "type": info["type"],
            "current": now,
            "node_count": len(all_nodes),
            "nodes": all_nodes,
            "is_current_in_list": now in all_nodes
        })

    return R.ok(
        data={"groups": result, "total": len(result)},
        message=f"共 {len(result)} 个代理组"
    )


def tool_list_nodes(**kwargs) -> dict:
    """列出指定代理组的节点及延迟。不指定则列出所有组。"""
    group = kwargs.get("group", "")
    groups = get_proxy_groups()
    if groups is None or "_mcp_error" in groups:
        return R.api_error("/proxies", "无法获取代理组")

    if group:
        if group not in groups:
            return R.not_found("proxy_group", group, list(groups.keys()))
        targets = {group: groups[group]}
    else:
        targets = groups

    result = []
    for gname, ginfo in targets.items():
        all_nodes = ginfo.get("all", [])
        now = ginfo.get("now", "N/A")
        nodes_info = []

        for node in all_nodes:
            encoded = urllib.parse.quote(node, safe='')
            delay_data = safe_api_get(
                f"/proxies/{encoded}/delay"
                f"?url={urllib.parse.quote(TEST_URL)}"
                f"&timeout={TEST_TIMEOUT}",
                timeout=8
            )
            if "_mcp_error" in delay_data:
                nodes_info.append({
                    "name": node, "delay_ms": None,
                    "is_current": node == now,
                    "error": delay_data["_mcp_error"]["error"]["code"],
                    "status": "timeout"
                })
            else:
                delay = delay_data.get("delay")
                nodes_info.append({
                    "name": node, "delay_ms": delay,
                    "is_current": node == now,
                    "error": None,
                    "status": "ok" if delay else "no_response"
                })

        result.append({
            "group_name": gname,
            "group_type": ginfo["type"],
            "current": now,
            "nodes": nodes_info,
            "total": len(nodes_info),
            "available": sum(1 for n in nodes_info if n["status"] == "ok")
        })

    return R.ok(
        data={"groups": result},
        message=f"已测试 {len(result)} 个组"
    )


def tool_switch_node(**kwargs) -> dict:
    """切换指定代理组的节点。"""
    group = kwargs.get("group", "")
    node = kwargs.get("node", "")

    if not group:
        return R.invalid_param("group", "代理组名称不能为空")
    if not node:
        return R.invalid_param("node", "节点名称不能为空")

    groups = get_proxy_groups()
    if groups is None or "_mcp_error" in groups:
        return R.api_error("/proxies", "无法获取代理组")

    if group not in groups:
        return R.not_found("proxy_group", group, list(groups.keys()))

    if node not in groups[group].get("all", []):
        return R.fail(
            code="NODE_NOT_IN_GROUP",
            message=f"节点 '{node}' 不在代理组 '{group}' 中",
            details=f"代理组 '{group}' 有 {len(groups[group]['all'])} 个节点"
                    f"，当前选择 '{groups[group].get('now', 'N/A')}'",
            suggestions=[f"使用 list_nodes 查看 '{group}' 中的可用节点",
                         "检查节点名称拼写是否完全一致"],
            affected=[node, group]
        )

    try:
        encoded = urllib.parse.quote(group, safe='')
        success = _api_put(f"/proxies/{encoded}", {"name": node})
        if success:
            return R.ok(
                data={
                    "group": group,
                    "previous": groups[group].get("now"),
                    "current": node
                },
                message=f"已切换: {group} → {node}"
            )
        return R.fail(
            code="SWITCH_FAILED",
            message=f"切换失败: {group} → {node}",
            details="Mihomo API 返回非 204 状态码",
            suggestions=["检查 Mihomo 是否正常运行",
                         "尝试手动切换: curl -X PUT ..."]
        )
    except Exception as e:
        return R.api_error(f"/proxies/{group}", str(e))


def tool_test_delay(**kwargs) -> dict:
    """测试指定代理节点的延迟。"""
    node = kwargs.get("node", "")
    url = kwargs.get("url", TEST_URL)
    timeout_ms = kwargs.get("timeout", TEST_TIMEOUT)

    if not node:
        return R.invalid_param("node", "节点名称不能为空")

    encoded = urllib.parse.quote(node, safe='')
    url_enc = urllib.parse.quote(url, safe='')
    try:
        req = urllib.request.Request(
            f"{MIHOMO_API}/proxies/{encoded}/delay"
            f"?url={url_enc}&timeout={timeout_ms}",
            headers={"User-Agent": "mcp-nodes/2.1"}
        )
        with urllib.request.urlopen(
            req, timeout=timeout_ms // 1000 + 3
        ) as resp:
            data = json.loads(resp.read())
            delay = data.get("delay")
            return R.ok(
                data={"node": node, "delay_ms": delay,
                      "test_url": url, "timeout_ms": timeout_ms},
                message=f"{node}: {delay}ms" if delay
                        else f"{node}: 无响应"
            )
    except urllib.error.HTTPError as e:
        return R.api_error(f"/proxies/{encoded}/delay",
                           f"HTTP {e.code}")
    except Exception as e:
        return R.timeout(f"测试 {node} 延迟",
                         timeout_ms // 1000 + 3)


def tool_test_connectivity(**kwargs) -> dict:
    """测试当前代理下能否访问指定目标URL。"""
    target = kwargs.get("target", "https://en.wikipedia.org")
    start = time.time()
    try:
        req = urllib.request.Request(
            target,
            headers={"User-Agent": "mcp-nodes/2.1"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed = time.time() - start
            return R.ok(
                data={
                    "target": target,
                    "status_code": resp.status,
                    "elapsed_seconds": round(elapsed, 2),
                    "size_bytes": len(resp.read())
                },
                message=f"✅ {target} 可达 ({round(elapsed, 2)}s, HTTP {resp.status})"
            )
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start
        return R.ok(
            data={
                "target": target,
                "status_code": e.code,
                "elapsed_seconds": round(elapsed, 2),
                "error": str(e)
            },
            message=f"⚠ {target} HTTP {e.code} ({round(elapsed, 2)}s)"
        )
    except urllib.error.URLError as e:
        elapsed = time.time() - start
        return R.fail(
            "CONNECTIVITY_FAILED",
            f"❌ {target} 不可达",
            details=f"{e.reason} ({round(elapsed, 2)}s)",
            suggestions=["换一个节点试试",
                         "检查目标网站是否被墙或已下线"]
        )
    except Exception as e:
        return R.fail("CONNECTIVITY_ERROR",
                       f"测试异常: {e}", details=str(e))


def tool_batch_test(**kwargs) -> dict:
    """遍历各节点逐一测试目标连通性，推荐最快节点。"""
    target = kwargs.get("target", "https://en.wikipedia.org")

    groups = get_proxy_groups()
    if groups is None or "_mcp_error" in groups:
        return R.api_error("/proxies",
                           "无法获取代理组列表")

    target_group = "🎯 手动选择"
    if target_group not in groups:
        # 尝试找第一个 Selector 组
        for gname, ginfo in groups.items():
            if ginfo.get("type") in ("Selector", "Select"):
                target_group = gname
                break
        if target_group not in groups:
            return R.not_found("proxy_group", "Selector",
                               list(groups.keys()))

    all_nodes = groups[target_group].get("all", [])
    current = groups[target_group].get("now", "")
    results = []
    best_node, best_time = None, float("inf")

    for node in all_nodes:
        # 切换节点
        try:
            encoded = urllib.parse.quote(target_group, safe='')
            _api_put(f"/proxies/{encoded}", {"name": node})
        except Exception:
            results.append({
                "node": node, "status": "switch_failed",
                "elapsed": None
            })
            continue

        time.sleep(0.3)

        # 测试连通性
        try:
            start = time.time()
            req = urllib.request.Request(
                target,
                headers={"User-Agent": "mcp-nodes/2.1"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                elapsed = time.time() - start
                status = "ok"
                if elapsed < best_time:
                    best_time = elapsed
                    best_node = node
                results.append({
                    "node": node, "status": "ok",
                    "elapsed": round(elapsed, 2),
                    "http_code": resp.status,
                    "is_current": node == current
                })
        except Exception:
            results.append({
                "node": node, "status": "timeout",
                "elapsed": None, "is_current": node == current
            })

    # 恢复原始节点
    try:
        encoded = urllib.parse.quote(target_group, safe='')
        _api_put(f"/proxies/{encoded}", {"name": current})
    except Exception:
        pass

    return R.ok(
        data={
            "target": target,
            "group": target_group,
            "total": len(results),
            "available": sum(1 for r in results
                             if r["status"] == "ok"),
            "best_node": best_node,
            "best_time_s": round(best_time, 2)
            if best_node else None,
            "details": results
        },
        message=f"共测试 {len(results)} 个节点，"
                f"{sum(1 for r in results if r['status'] == 'ok')} 个可达"
                + (f"，最快: {best_node} ({round(best_time, 2)}s)"
                   if best_node else "")
    )
