# -*- coding: utf-8 -*-
"""
临时测试入口：绕过「一天一条」去重，强制尝试打卡，用于验证 v6 接口。

用法（在 workflow 里）：
    python test_sign.py
只有 workflow_dispatch 手动触发时才需要，不进主流程。

⚠️ 这会真实产生打卡记录。仅用于接口验证。
"""
from modules.net_patch import force_ipv4
force_ipv4()

import json
import sys
import time

from modules.load_config import load_config
from modules.get_login_token import get_token
from modules.get_plan_id import get_plan_id
from modules.crypto_aes import create_sign
from modules.save_user_info import save_user_info

users = load_config()
if not users:
    print("没有读到配置")
    sys.exit(1)

for user in users:
    if not user.get("enable", True):
        continue
    phone = user["phone"]
    print("=" * 66)
    print("测试账号:", phone)
    print("=" * 66)

    info = get_token(user)
    if not isinstance(info, dict) or not info.get("token"):
        print("  登录失败:", info)
        continue
    token, uid = info["token"], info["userId"]
    print("  userId =", uid)

    plan_id = get_plan_id(user, token, create_sign(uid + "student"))
    print("  planId =", plan_id)

    # 直接调 save_user_info：它内部会依次试 v6/v2 × 6 种拼串
    print("\n  开始尝试打卡（会打印每种组合的结果）")
    ok, msg, resp = save_user_info(
        user, uid, token, plan_id,
        user["province"], user["address"],
        signType="START",
        latitude=user["latitude"],
        longitude=user["longitude"],
    )
    print("\n" + "-" * 66)
    print("最终结果:", "成功 ✓" if ok else "失败 ✗")
    print("msg:", msg)
    if resp:
        print("完整响应:", json.dumps(resp, ensure_ascii=False)[:400])
    print("-" * 66)
