"""
Mihomo REST API 封装。
提供统一接口调用 Mihomo 的外部控制器 API。
"""

import json
import urllib.request
import urllib.parse
import urllib.error

from config import MIHOMO_API, R


def _api_get(path: str, timeout: int = 10) -> dict:
    """GET 请求 Mihomo API，返回 JSON。"""
    url = f"{MIHOMO_API}{path}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "mcp-nodes/2.1"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _api_put(path: str, data: dict, timeout: int = 10) -> bool:
    """PUT 请求 Mihomo API，返回是否成功。"""
    url = f"{MIHOMO_API}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, method="PUT",
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status == 204


def safe_api_get(path: str, timeout: int = 10) -> dict:
    """
    安全 GET，异常时返回含 _mcp_error 的 dict，
    调用方需自行检查 "_mcp_error" 键。
    """
    try:
        return _api_get(path, timeout)
    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode(errors="replace")
        return {"_mcp_error": R.api_error(
            path, f"HTTP {e.code}: {body}")}
    except urllib.error.URLError as e:
        return {"_mcp_error": R.api_error(
            path, f"URLError: {e.reason}")}
    except OSError as e:
        return {"_mcp_error": R.api_error(
            path, f"OSError: {e}")}
    except Exception as e:
        return {"_mcp_error": R.api_error(
            path, f"{type(e).__name__}: {e}")}


def get_proxy_groups() -> dict | None:
    """获取所有代理组信息。"""
    data = safe_api_get("/proxies")
    if "_mcp_error" in data:
        return data
    raw = data.get("proxies", data)
    groups = {}
    for name, info in raw.items():
        if isinstance(info, dict) and info.get("type") in (
            "Selector", "URLTest", "Select", "Fallback", "LoadBalance"
        ):
            groups[name] = info
    return groups


def switch_proxy_node(group: str, node: str) -> dict:
    """切换指定代理组的节点。"""
    encoded = urllib.parse.quote(group, safe="")
    path = f"/groups/{encoded}"
    raw = safe_api_get(path)
    if "_mcp_error" in raw:
        return raw["_mcp_error"]

    try:
        _api_put(f"{path}/delay", {"name": node})
        return R.ok(message=f"节点已切换: {group} → {node}")
    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode(errors="replace")
        return R.fail(
            "SWITCH_FAILED",
            f"切换节点 '{node}' 失败",
            details=f"HTTP {e.code}: {body}",
            suggestions=["确认节点名称拼写", "检查代理组名称"]
        )
    except Exception as e:
        return R.fail(
            "SWITCH_ERROR",
            f"切换异常: {e}",
            details=f"{type(e).__name__}: {e}"
        )


def test_node_delay(node: str, url: str = None,
                    timeout: int = None) -> dict:
    """测试单个节点延迟。"""
    from config import TEST_URL, TEST_TIMEOUT
    target_url = url or TEST_URL
    t = timeout or TEST_TIMEOUT
    params = urllib.parse.urlencode({
        "name": node, "url": target_url, "timeout": str(t)
    })
    path = f"/group/{urllib.parse.quote(node, safe='')}/delay?{params}"
    raw = safe_api_get(path)
    if "_mcp_error" in raw:
        return {"_mcp_error": raw["_mcp_error"]}

    delay = raw.get(node) or raw.get("delay")
    if delay is not None:
        return {"delay": int(delay)}
    return {"delay": None, "raw": str(raw)[:200]}
