"""
Mihomo 规则管理工具。
支持查看、添加、删除流量路由规则（DOMAIN/IP-CIDR/GEOIP 等）。
"""

import re
from config import MIHOMO_CONFIG, R
from config_manager import read_config, write_config, restart_mihomo

# ─── 支持的规则类型 ─────────────────────────────────

RULE_TYPES = [
    "DOMAIN",           # 完整域名匹配
    "DOMAIN-SUFFIX",    # 域名后缀匹配
    "DOMAIN-KEYWORD",   # 域名关键词匹配
    "DOMAIN-REGEX",     # 域名正则匹配
    "IP-CIDR",          # IP 段匹配
    "IP-CIDR6",         # IPv6 段匹配
    "SRC-IP-CIDR",      # 源 IP 段匹配
    "SRC-PORT",         # 源端口匹配
    "DST-PORT",         # 目标端口匹配
    "PROCESS-NAME",     # 进程名匹配
    "PROCESS-PATH",     # 进程路径匹配
    "GEOIP",            # GeoIP 国家匹配
    "GEOSITE",          # GeoSite 站点匹配
    "MATCH",            # 兜底匹配（必须在最后）
    "RULE-SET",         # 规则集
    "AND",              # 与逻辑
    "OR",               # 或逻辑
    "NOT",              # 非逻辑
    "SUB-RULE",         # 子规则
]

# ─── 规则解析 ──────────────────────────────────────


def _parse_rule(rule_str: str) -> dict | None:
    """将规则字符串解析为结构化 dict。"""
    if isinstance(rule_str, dict):
        return rule_str  # 已经是结构化格式
    parts = [p.strip() for p in str(rule_str).split(",")]
    if len(parts) < 2:
        return None
    rule_type = parts[0]
    if rule_type not in RULE_TYPES and not rule_type.startswith("RULE-SET"):
        return None

    parsed = {"type": rule_type, "raw": rule_str}

    if rule_type == "MATCH":
        parsed["policy"] = parts[1] if len(parts) > 1 else ""
        parsed["display"] = f"MATCH → {parsed['policy']}"
    elif rule_type in ("GEOIP", "GEOSITE"):
        parsed["country"] = parts[1] if len(parts) > 1 else ""
        parsed["policy"] = parts[2] if len(parts) > 2 else "DIRECT"
        parsed["display"] = f"{rule_type},{parsed['country']} → {parsed['policy']}"
    elif rule_type in ("RULE-SET",):
        parsed["rule_set"] = parts[1] if len(parts) > 1 else ""
        parsed["policy"] = parts[2] if len(parts) > 2 else "DIRECT"
        parsed["display"] = f"{rule_type},{parsed['rule_set']} → {parsed['policy']}"
    elif rule_type in ("DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "DOMAIN-REGEX"):
        parsed["match"] = parts[1] if len(parts) > 1 else ""
        parsed["policy"] = parts[2] if len(parts) > 2 else "DIRECT"
        parsed["display"] = f"{rule_type},{parsed['match']} → {parsed['policy']}"
    elif rule_type in ("IP-CIDR", "IP-CIDR6", "SRC-IP-CIDR"):
        parsed["cidr"] = parts[1] if len(parts) > 1 else ""
        parsed["policy"] = parts[2] if len(parts) > 2 else "DIRECT"
        no_resolve = "no-resolve" in parts
        parsed["no_resolve"] = str(no_resolve).lower()
        parsed["display"] = f"{rule_type},{parsed['cidr']} → {parsed['policy']}" + (
            " (no-resolve)" if no_resolve else "")
    elif rule_type in ("SRC-PORT", "DST-PORT"):
        parsed["port"] = parts[1] if len(parts) > 1 else ""
        parsed["policy"] = parts[2] if len(parts) > 2 else "DIRECT"
        parsed["display"] = f"{rule_type},{parsed['port']} → {parsed['policy']}"
    elif rule_type in ("PROCESS-NAME", "PROCESS-PATH"):
        parsed["match"] = parts[1] if len(parts) > 1 else ""
        parsed["policy"] = parts[2] if len(parts) > 2 else "DIRECT"
        parsed["display"] = f"{rule_type},{parsed['match']} → {parsed['policy']}"
    else:
        parsed["policy"] = parts[-1]
        parsed["display"] = rule_str

    return parsed


def _format_rule(rule_type: str, match: str, policy: str,
                 no_resolve: bool = False) -> str:
    """将参数格式化为规则字符串。"""
    parts = [rule_type, match, policy]
    if no_resolve and rule_type in ("IP-CIDR", "IP-CIDR6", "SRC-IP-CIDR"):
        parts.append("no-resolve")
    return ",".join(parts)


def _find_builtin_position(rules: list) -> int:
    """找到内置规则（GEOSITE/GEOIP/MATCH）的起始位置。"""
    for i, r in enumerate(rules):
        r_str = r if isinstance(r, str) else ""
        if any(r_str.startswith(p) for p in ("GEOSITE,", "GEOIP,", "MATCH,")):
            return i
    return len(rules)


def _rule_matches(rule_str: str, search: str) -> bool:
    """检查规则是否匹配搜索关键词。"""
    return search.lower() in rule_str.lower()


# ─── 工具函数 ──────────────────────────────────────


def tool_list_rules(**kwargs) -> dict:
    """列出当前所有规则。"""
    cfg = read_config()
    if cfg is None:
        return R.fail("CONFIG_ERROR", "无法读取配置文件",
                       details=f"检查 {MIHOMO_CONFIG} 是否存在",
                       suggestions=["sudo cat /etc/mihomo/config.yaml"])

    rules = cfg.get("rules", [])
    if not rules:
        return R.ok(data={"rules": [], "total": 0},
                     message="暂无规则")

    filter_text = kwargs.get("filter", "")
    parsed_rules = []
    for r in rules:
        parsed = _parse_rule(r)
        if filter_text and not _rule_matches(str(r), filter_text):
            continue
        if parsed:
            parsed_rules.append(parsed)
        else:
            parsed_rules.append({"raw": str(r), "display": str(r)})

    return R.ok(
        data={
            "rules": parsed_rules,
            "total": len(parsed_rules),
            "raw_rules": rules if not filter_text else [
                r for r in rules if _rule_matches(str(r), filter_text)
            ],
        },
        message=f"共 {len(parsed_rules)} 条规则"
    )


def tool_add_rule(**kwargs) -> dict:
    """添加一条新规则。"""
    rule_type = kwargs.get("type", "DOMAIN-SUFFIX")
    match = kwargs.get("match", "")
    policy = kwargs.get("policy", "DIRECT")
    position = kwargs.get("position", "auto")
    no_resolve = kwargs.get("no_resolve", False)
    skip_restart = kwargs.get("skip_restart", False)

    if not match and rule_type not in ("MATCH",):
        return R.invalid_param("match", "匹配值不能为空")
    if not policy:
        return R.invalid_param("policy", "策略目标不能为空")

    rule_str = _format_rule(rule_type, match, policy, no_resolve)

    cfg = read_config()
    if cfg is None:
        return R.fail("CONFIG_ERROR", "无法读取配置文件")

    rules = cfg.get("rules", [])

    # 检查是否已存在相同规则
    if rule_str in rules:
        return R.fail(
            "RULE_EXISTS",
            f"规则已存在: {rule_str}",
            suggestions=["使用 list_rules 查看现有规则",
                         "使用 remove_rule 删除旧规则后再添加"],
            affected=[rule_str]
        )

    # 确定插入位置
    if position == "auto":
        idx = _find_builtin_position(rules)
    elif position == "first":
        idx = 0
    elif position == "last":
        idx = len(rules)
    elif position == "before_geop":
        idx = _find_builtin_position(rules)
    else:
        try:
            idx = int(position)
        except ValueError:
            idx = _find_builtin_position(rules)

    rules.insert(idx, rule_str)
    cfg["rules"] = rules

    ok, msg = write_config(cfg)
    if not ok:
        return R.config_error(msg)

    result = {
        "rule": rule_str,
        "position": idx,
        "total_rules": len(rules),
    }

    if not skip_restart:
        ok2, msg2 = restart_mihomo()
        if not ok2:
            return R.ok(
                data={**result, "restart_failed": True},
                message=f"规则已添加但 Mihomo 重启失败: {msg2}"
            )
        result["restarted"] = True
        return R.ok(
            data=result,
            message=f"✅ 已添加规则并重启: {rule_str}"
        )

    return R.ok(data=result, message=f"✅ 规则已添加（未重启）: {rule_str}")


def tool_remove_rule(**kwargs) -> dict:
    """删除匹配的规则。"""
    rule_type = kwargs.get("type", "")
    match = kwargs.get("match", "")
    policy = kwargs.get("policy", "")
    index = kwargs.get("index", -1)
    all_matches = kwargs.get("all", False)
    skip_restart = kwargs.get("skip_restart", False)

    cfg = read_config()
    if cfg is None:
        return R.fail("CONFIG_ERROR", "无法读取配置文件")

    rules = cfg.get("rules", [])
    if not rules:
        return R.ok(data={"removed": 0}, message="当前没有规则")

    # 按索引删除
    if index >= 0:
        if index >= len(rules):
            return R.invalid_param("index",
                                   f"索引超出范围（0-{len(rules)-1}）")
        removed = rules.pop(index)
        cfg["rules"] = rules
        ok, msg = write_config(cfg)
        if not ok:
            return R.config_error(msg)
        result = {"removed": [removed], "index": index}
        if not skip_restart:
            restart_mihomo()
            result["restarted"] = True
        return R.ok(data=result,
                     message=f"✅ 已删除规则: {removed}")

    # 按条件匹配删除
    if not rule_type and not match and not policy:
        return R.invalid_param("条件",
                               "请指定 type/match/policy/index 中的一个或多个")

    before = len(rules)
    remaining = []
    removed = []

    for idx, r in enumerate(rules):
        r_str = str(r)
        match_type = (
            not rule_type
            or r_str.startswith(rule_type + ",")
            or r_str == rule_type
        )
        match_policy = not policy or r_str.endswith("," + policy)
        match_value = not match or match.lower() in r_str.lower()

        if match_type and match_policy and match_value:
            if all_matches:
                removed.append(r)
                continue
            else:
                # 只删第一个匹配的
                removed.append(r)
                remaining.extend(rules[idx + 1:])
                break
        remaining.append(r)
    else:
        # 删到最后一个也没 break（表示全删了或者没匹配到）
        pass

    if not removed:
        return R.fail("RULE_NOT_FOUND",
                       "未找到匹配的规则",
                       suggestions=["使用 list_rules 查看现有规则",
                                    "检查 type/match/policy 是否正确"])

    cfg["rules"] = remaining
    ok, msg = write_config(cfg)
    if not ok:
        return R.config_error(msg)

    result = {
        "removed": removed,
        "removed_count": len(removed),
        "remaining_count": len(remaining),
    }

    if not skip_restart:
        ok2, msg2 = restart_mihomo()
        if not ok2:
            return R.ok(
                data={**result, "restart_failed": True},
                message=f"规则已删除但重启失败: {msg2}"
            )
        result["restarted"] = True
        return R.ok(data=result,
                     message=f"✅ 已删除 {len(removed)} 条规则并重启")

    return R.ok(data=result,
                 message=f"✅ 已删除 {len(removed)} 条规则（未重启）")


def tool_add_direct_rule(**kwargs) -> dict:
    """快捷添加一条直连规则（域名/IP 走 DIRECT）。"""
    kwargs["policy"] = "DIRECT"
    return tool_add_rule(**kwargs)


def tool_add_proxy_rule(**kwargs) -> dict:
    """快捷添加一条代理规则（域名/IP 走指定代理组）。"""
    if not kwargs.get("policy"):
        kwargs["policy"] = "🌐 国外流量"
    return tool_add_rule(**kwargs)
