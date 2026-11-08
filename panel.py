#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
工学云打卡面板 —— 本地 Web 服务

为什么是本地服务而不是纯静态页：
  工学云接口需要 access token（来自登录），且跨域请求会被浏览器拦，
  所以必须由一个本地进程代持 token 并转发请求。浏览器只跟 127.0.0.1 通信。

启动：python panel.py            （自动开浏览器）
      python panel.py --no-open  （不自动开，便于调试）
      python panel.py --port 8765

安全：
  - 只监听 127.0.0.1，不暴露到局域网
  - 账号密码存在 credentials.json（已 gitignore），只在启动时读一次
  - 服务本身不做任何写操作，唯一的动作是「触发 GitHub Actions」
"""

import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PWD = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PWD)

import requests

# 复用已验证过的登录/请求头逻辑，避免面板和主程序行为漂移
from modules.get_login_token import get_token
from modules.map_headers import header_user_agent
from modules.crypto_aes import create_sign

TZ = timezone(timedelta(hours=8))
CLOCK_URL = "https://api.moguding.net:9000/attendence/clock/v2/listSynchro"
CRED_FILE = os.path.join(PWD, "credentials.json")
TOKEN_FILE = os.path.join(PWD, "gh_token.txt")

# ---------------------------------------------------------------- 凭证与登录态
class Auth:
    """缓存 token（默认 2 小时），避免每次刷新面板都登录一次触发风控。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.token = None
        self.user_id = None        # get_token 返回的键名就是 userId
        self.expire_at = 0
        self.last_error = None
        self.phone = None

    def _load_cred(self):
        if not os.path.exists(CRED_FILE):
            raise RuntimeError("缺少 credentials.json")
        with open(CRED_FILE, encoding="utf-8") as f:
            c = json.load(f)
        if not c.get("phone") or not c.get("password"):
            raise RuntimeError("credentials.json 里 phone/password 为空")
        return c

    def get(self, force=False):
        with self.lock:
            if not force and self.token and time.time() < self.expire_at:
                return self.token
            cred = self._load_cred()
            self.phone = cred["phone"]
            user = {
                "remark": "panel",
                "phone": cred["phone"],
                "password": cred["password"],
                "user-agent": "null",
            }
            try:
                info = get_token(user)
            except Exception as exc:
                self.last_error = "登录异常: %s" % exc
                raise RuntimeError(self.last_error)
            if not isinstance(info, dict) or not info.get("token"):
                self.last_error = "登录失败: %s" % (
                    info.get("msg") if isinstance(info, dict) else info)
                raise RuntimeError(self.last_error)
            self.token = info["token"]
            self.user_id = info.get("userId")
            self.expire_at = time.time() + 2 * 3600
            self.last_error = None
            return self.token

    def headers(self, user_extra=None):
        user = {"user-agent": "null"}
        h = {
            "Authorization": self.get(),
            "roleKey": "student",
            "content-type": "application/json; charset=UTF-8",
            "user-agent": header_user_agent(user),
        }
        return h


AUTH = Auth()


# ---------------------------------------------------------------- 数据获取
def fetch_records(days=45):
    end = datetime.now(TZ)
    start = end - timedelta(days=days)
    body = {
        "startTime": start.strftime("%Y-%m-%d 00:00:00"),
        "endTime": end.strftime("%Y-%m-%d 23:59:59"),
    }
    r = requests.post(CLOCK_URL, json=body, headers=AUTH.headers(), timeout=30)
    j = r.json()
    if j.get("code") != 200:
        raise RuntimeError("查询失败 code=%s msg=%s" % (j.get("code"), j.get("msg")))
    return j.get("data") or []


def build_summary(records):
    """按日期聚合，给出日历需要的结构。"""
    by_date = {}
    for rec in records:
        day = str(rec.get("createTime", ""))[:10]
        if not day:
            continue
        by_date.setdefault(day, []).append({
            "type": rec.get("type"),
            "time": str(rec.get("createTime", ""))[11:19],
            "address": rec.get("address", ""),
            "longitude": rec.get("longitude"),
            "latitude": rec.get("latitude"),
            "state": rec.get("state"),
        })

    for day in by_date:
        by_date[day].sort(key=lambda x: x["time"])

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    # 生成连续 N 天序列（含无记录的日子），供日历渲染
    days = sorted(by_date.keys())
    # 注意：strptime 出来的是 naive datetime，而 datetime.now(TZ) 带时区，
    # 直接相减会抛 "can't subtract offset-naive and offset-aware datetimes"。
    # 所以这里统一用 naive 本地时间做日期运算。
    now_naive = datetime.now(TZ).replace(tzinfo=None)
    if days:
        first = datetime.strptime(days[0], "%Y-%m-%d")
    else:
        first = now_naive - timedelta(days=27)
    span = (now_naive - first).days + 1
    span = max(1, min(span, 120))          # 上限防止异常数据把日历拉爆
    calendar = []
    for i in range(span):
        dt = first + timedelta(days=i)
        d = dt.strftime("%Y-%m-%d")
        recs = by_date.get(d, [])
        calendar.append({
            "date": d,
            "count": len(recs),
            "records": recs,
            "weekday": dt.weekday(),
        })

    today_recs = by_date.get(today, [])
    # 连续打卡天数。
    # 加硬上限：若 by_date 数据异常或 probe 逻辑出岔子，while True 会卡死整个请求，
    # 所以按「最多回看一年」封顶，同时避免扫描过大。
    streak = 0
    probe = datetime.now(TZ).replace(tzinfo=None)
    for _ in range(366):
        key = probe.strftime("%Y-%m-%d")
        if key in by_date:
            streak += 1
            probe -= timedelta(days=1)
        else:
            # 今天还没打不算断，从昨天起算
            if key == today:
                probe -= timedelta(days=1)
                continue
            break

    return {
        "server_time": datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "today": today,
        "today_records": today_recs,
        "today_done": len(today_recs) > 0,
        "total_records": len(records),
        "calendar": calendar,
        "streak": streak,
        "phone": AUTH.phone,
        "user_id": AUTH.user_id,
    }


# ---------------------------------------------------------------- GitHub 侧
def gh_headers():
    if not os.path.exists(TOKEN_FILE):
        return None
    tok = open(TOKEN_FILE, encoding="utf-8").read().strip()
    if not tok:
        return None
    return {
        "Authorization": "Bearer " + tok,
        "Accept": "application/vnd.github+json",
        "User-Agent": "gxy-panel",
    }


GH_REPO = "dsh-z/Auto-GongXueYun"


def fetch_runs(limit=8):
    h = gh_headers()
    if not h:
        return {"error": "未找到 gh_token.txt，无法读取运行记录"}
    try:
        r = requests.get(
            "https://api.github.com/repos/%s/actions/runs?per_page=%d" % (GH_REPO, limit),
            headers=h, timeout=25)
        if r.status_code != 200:
            return {"error": "GitHub API %s: %s" % (r.status_code, r.text[:120])}
        runs = r.json().get("workflow_runs") or []
        out = []
        for x in runs:
            out.append({
                "id": x["id"],
                "status": x["status"],
                "conclusion": x.get("conclusion"),
                "event": x.get("event"),
                "created": x["created_at"],
                "url": x["html_url"],
            })
        return {"runs": out}
    except Exception as exc:
        return {"error": str(exc)}


def trigger_run():
    h = gh_headers()
    if not h:
        return {"ok": False, "error": "未找到 gh_token.txt"}
    try:
        w = requests.get("https://api.github.com/repos/%s/actions/workflows" % GH_REPO,
                         headers=h, timeout=25)
        wfs = (w.json() or {}).get("workflows") or []
        if not wfs:
            return {"ok": False, "error": "仓库里没有 workflow"}
        wid = wfs[0]["id"]
        r = requests.post(
            "https://api.github.com/repos/%s/actions/workflows/%s/dispatches" % (GH_REPO, wid),
            headers=h, json={"ref": "main"}, timeout=25)
        if r.status_code in (204, 201, 200):
            return {"ok": True, "message": "已触发，约 1~2 分钟后可在下方运行记录看到"}
        return {"ok": False, "error": "HTTP %s: %s" % (r.status_code, r.text[:150])}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------- HTTP 服务
class Handler(BaseHTTPRequestHandler):
    server_version = "GXYPanel/1.0"

    def log_message(self, fmt, *args):
        # 静音默认访问日志，避免控制台刷屏
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            # ensure_ascii=False 保留中文可读；浏览器按 charset=utf-8 正确解码
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        # 明确声明编码，避免 curl / PowerShell 等工具按系统代码页(GBK)误解码，
        # 从而把正常的中文显示成乱码、或被误判成"数据损坏"。
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                page = os.path.join(PWD, "panel.html")
                with open(page, encoding="utf-8") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
                return
            if path == "/api/summary":
                try:
                    recs = fetch_records()
                    self._send(200, build_summary(recs))
                except Exception as exc:
                    AUTH.reset()
                    self._send(200, {"error": str(exc)})
                return
            if path == "/api/runs":
                self._send(200, fetch_runs())
                return
            if path == "/api/trigger":
                self._send(200, trigger_run())
                return
            self._send(404, {"error": "not found"})
        except Exception as exc:
            self._send(500, {"error": str(exc)})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if path == "/api/trigger":
            self._send(200, trigger_run())
        else:
            self._send(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    # 端口被占用时自动顺延，避免快捷方式因旧进程残留而打不开
    port = args.port
    srv = None
    for p in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if srv is None:
        print("找不到可用端口，请关闭占用 %d 的程序" % args.port)
        return 1

    url = "http://127.0.0.1:%d/" % port
    print("工学云打卡面板已启动: %s" % url)
    print("按 Ctrl+C 停止")
    if not args.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
