# -*- coding: utf-8 -*-
"""
强制 IPv4：解决 GitHub Actions 上 "Network is unreachable"。

问题根因（实测确认，不是猜测）：
  api.moguding.net 的 DNS 同时返回 IPv4 与 6to4 IPv6：
      118.190.120.71
      2002::76be:7847     <- 6to4 地址，在 GitHub runner 上不可达
  Python 的 socket.getaddrinfo 默认按 RFC 3484 排序，IPv6 优先级更高，
  于是 urllib3 先连 IPv6 -> [Errno 101] Network is unreachable，
  且不会自动回退到 IPv4，整个请求直接失败。

  而 curl 自带 Happy Eyeballs（快速回退），所以诊断里 curl 是通的、
  Python 脚本是断的 —— 这个差异正是定位线索。

修复方式：
  包装 socket.getaddrinfo，过滤掉 AF_INET6 结果，强制走 IPv4。
  只对本进程生效，不影响系统配置。
"""
import socket

_orig_getaddrinfo = socket.getaddrinfo
_patched = False


def force_ipv4():
    """把 getaddrinfo 限制为只返回 IPv4 结果。"""
    global _patched
    if _patched:
        return

    def ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
        results = _orig_getaddrinfo(host, port, family, type, proto, flags)
        only4 = [r for r in results if r[0] == socket.AF_INET]
        # 万一只返回了 IPv6（极少数情况），保留原结果避免彻底不可用
        return only4 if only4 else results

    socket.getaddrinfo = ipv4_only
    _patched = True

    # 同步影响 requests/urllib3 里已导入的引用
    try:
        import urllib3.util.connection as uc
        uc.allowed_gai_family = lambda: socket.AF_INET
    except Exception:
        pass
