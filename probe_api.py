# -*- coding: utf-8 -*-
"""对比不同请求头，定位 403 的真实原因（IP 封禁 vs 缺 header）。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from modules.get_login_token import get_token
from modules.check_sign_in import get_current_day
from modules.crypto_aes import create_sign

user = {
    "remark": "probe", "phone": "18182794174", "password": "Mingyang21",
    "province": "安徽省", "city": "芜湖市", "area": "鸠江区",
    "address": "安徽省 · 芜湖市 · 鸠江区 · 奇瑞汽车股份有限公司",
    "longitude": "118.368233", "latitude": "31.426823",
    "randomLocation": False, "enable": True, "desc": "probe", "pushKey": "",
}

info = get_token(user)
token = info["token"]
uid = info["userId"]
sign = create_sign(uid + "student")
s, e = get_current_day()

UA = ("Mozilla/5.0 (Linux; Android 10; LIO-AN00 Build/HUAWEILIO-AN00; wv) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/67.0.3396.87 "
      "XWEB/1170 Mobile Safari/537.36")

urls = [
    "https://api.moguding.net:9000/attendence/clock/v2/listSynchro",
    "https://api.moguding.net:9000/attendence/clock/v1/listSynchro",
]

variants = [
    ("原版(仅 Authorization)", {"Authorization": token}),
    ("+roleKey+UA", {"Authorization": token, "roleKey": "student", "user-agent": UA}),
    ("完整头(+sign+content-type)", {
        "Authorization": token, "roleKey": "student", "user-agent": UA,
        "sign": sign, "content-type": "application/json; charset=UTF-8",
        "accept-encoding": "gzip"}),
]

bodies = [
    ("json参数", {"startTime": s, "endTime": e}),
    ("空body", {}),
]

for url in urls:
    print("\n" + "=" * 60)
    print(url.rsplit("/", 2)[1] + "  " + url.rsplit("/", 1)[1])
    for vname, hdr in variants:
        for bname, body in bodies:
            try:
                r = requests.post(url, json=body, headers=hdr, timeout=25)
                try:
                    j = r.json()
                    code = j.get("code")
                    msg = str(j.get("msg"))[:70]
                    keys = ",".join(list(j.keys())[:5])
                    data_len = len(j["data"]) if isinstance(j.get("data"), list) else "N/A"
                    print("  %-24s %-8s -> code=%-5s data_len=%-4s keys=[%s] msg=%s"
                          % (vname, bname, code, data_len, keys, msg))
                except Exception:
                    print("  %-24s %-8s -> 非JSON: %s" % (vname, bname, r.text[:60]))
            except Exception as exc:
                print("  %-24s %-8s -> 异常 %s" % (vname, bname, str(exc)[:50]))
