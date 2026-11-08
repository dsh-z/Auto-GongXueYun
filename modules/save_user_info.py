import json
import os
import time

import requests

from modules.map_headers import header_user_agent
from modules.crypto_aes import create_sign

# ---------------------------------------------------------------------------
# 打卡提交
#
# 关键背景（从 APK 反编译确认，别再猜）：
#   App 5.43.6 实际调用的是  /attendence/clock/v6/save
#   而所有开源项目都还在打 /attendence/clock/v2/save
#   服务端对 v2 返回 code=500「请到应用商店或者工学云网站下载最新版本APP」
#   —— 这句提示会让人误以为是版本号 header 问题，其实是接口代次落后。
#
#   签名密钥经确认仍是 3478cbbc33f84bd00d75d7dfa69e0daa（与旧版一致），
#   即 MD5(拼串 + KEY)，所以变量只在路径版本和拼串顺序。
#
# 本实现先打 v6，按多套拼串顺序回退；全部失败再退回 v2 做对照。
# 一旦某套组合成功，会用环境变量 GXY_SIGN_MODE 记录下来供下次直接用。
# ---------------------------------------------------------------------------

BASE = "https://api.moguding.net:9000"

# 候选签名拼串规则：(名称, 拼串函数)
# 把可能变化的部分做成表，避免每次都要改代码重新部署验证。
SIGN_VARIANTS = [
    ("v2_order", lambda d, t, p, u, a, c: d + t + p + u + a),
    ("with_country", lambda d, t, p, u, a, c: d + t + p + u + a + c),
    ("user_first", lambda d, t, p, u, a, c: u + d + t + p + a),
    ("plan_first", lambda d, t, p, u, a, c: p + d + t + u + a),
    ("no_device", lambda d, t, p, u, a, c: t + p + u + a),
    ("addr_first", lambda d, t, p, u, a, c: a + d + t + p + u),
]

# 默认先用最可能的：v6 + 原版顺序
DEFAULT_ORDER = "v2_order"
API_VERSIONS = ("v6", "v2")


def _build_data(user, planId, signType, device, province, address, latitude, longitude):
    return {
        "country": "中国",
        "address": address,
        "province": province,
        "city": user["city"],
        "area": user["area"],
        "latitude": latitude,
        "description": user["desc"],
        "planId": planId,
        "type": signType,
        "device": device,
        "longitude": longitude,
    }


def _post(url, headers, data, retries=2):
    last = None
    for i in range(retries):
        try:
            res = requests.post(url=url, headers=headers, data=json.dumps(data), timeout=30)
            try:
                return res.json()
            except json.JSONDecodeError:
                return {"code": -1, "msg": "非JSON响应: " + res.text[:120]}
        except Exception as exc:
            last = exc
            time.sleep(2)
    return {"code": -1, "msg": "请求异常: %s" % last}


def save_user_info(
    user,
    userId,
    token,
    planId,
    province,
    address,
    signType="START",
    device="Android",
    latitude=None,
    longitude=None,
):
    """提交打卡。成功返回 (True, msg, 完整响应)，失败返回 (False, msg, 最后一次响应)。"""
    data = _build_data(user, planId, signType, device, province, address,
                       latitude, longitude)

    # 若上次已探明可用组合，优先单发那一套，避免每次都把全部组合跑一遍
    preferred = os.environ.get("GXY_SIGN_MODE", "").strip()
    order = [v for v in SIGN_VARIANTS if v[0] == preferred] + \
            [v for v in SIGN_VARIANTS if v[0] != preferred]

    last_resp = None
    for ver in API_VERSIONS:
        url = "%s/attendence/clock/%s/save" % (BASE, ver)
        for name, fn in order:
            text = fn(device, signType, planId, userId, address, "中国")
            headers = {
                "roleKey": "student",
                "user-agent": header_user_agent(user),
                "sign": create_sign(text),
                "authorization": token,
                "content-type": "application/json; charset=UTF-8",
            }
            resp = _post(url, headers, data)
            last_resp = resp
            code = resp.get("code")
            msg = str(resp.get("msg", ""))
            print("    [try] %s/%-12s -> code=%s %s" % (ver, name, code, msg[:50]))

            if code == 200:
                print("    >>> 命中: %s + %s" % (ver, name))
                # 提示：把该值写进仓库变量 GXY_SIGN_MODE 可跳过后续探索
                print("    >>> 建议设置 environment: GXY_SIGN_MODE=%s" % name)
                return True, msg, resp

            # 版本不匹配时换下一个 API 版本更有意义，不必把所有拼串试完
            if "最新版本" in msg or "下载最新" in msg:
                print("    [ver-mismatch] 换下一个接口版本")
                break
            time.sleep(1.2)

    if last_resp is None:
        return False, "所有尝试均未返回", None
    return False, str(last_resp.get("msg", "")), last_resp
