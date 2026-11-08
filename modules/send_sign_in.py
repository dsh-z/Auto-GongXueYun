import random
import threading
import json
import requests
from modules.get_plan_id import get_plan_id
from modules.get_login_token import get_token
from modules.crypto_aes import create_sign
from modules.check_sign_in import check_sign
from modules.save_user_info import save_user_info
from datetime import datetime, timezone, timedelta
from modules.load_config import dprint


# 操作地时区设置
shanghai_tz = timezone(timedelta(hours=8))
gmt_time = datetime.now(shanghai_tz)
now = datetime.now(shanghai_tz)

# ---------------------------------------------------------------------------
# 打卡策略：每天只要一条记录
#
# 原版按「12 点前=上班 START / 12 点后=下班 END」区分，需要一天跑两次。
# 这里改为：每次运行只尝试补一条，且当天已有任意记录就直接跳过。
# 因此无论一天触发多少次（开机、定时、手动），实际最多只产生一条打卡记录。
#
# 为什么固定发 START：工学云的「上班卡」是当日第一条记录，重复提交 END
# 容易变成两条不同业务类型的记录，反而更显眼。一天一次 = 一条 START 最干净。
# ---------------------------------------------------------------------------
DAILY_SIGN_TYPE = "START"
sign_type_mapping = {"START": "上班", "END": "下班"}

# 收集所有线程签到结果
global_sign_results = []
# 覆盖打卡，设置为 True 会导致每次运行都不检查历史从而重复签到，仅调试用
RepeatCheckIn = False


# 处理单个用户的签到流程：登录 -> 取 planId -> 查今日记录 -> 必要时补一条
def send_sign_in(user_info, timeout):
    try:
        timer = threading.Timer(timeout, lambda: None)
        timer.start()
        phone = user_info["phone"]
        remark = user_info.get("remark", "")
        prefix = f"[{remark}/{phone}]"

        # 随机化经纬度（末位抖动，避免长期同一坐标）
        if user_info.get("randomLocation", False):
            user_info["latitude"] = user_info["latitude"][0:-1] + str(random.randint(0, 9))
            user_info["longitude"] = user_info["longitude"][0:-1] + str(random.randint(0, 9))

        # 先查登录结果，避免在失败时继续用空 dict 取值
        try:
            userInfo = get_token(user_info)
        except Exception as e:
            msg = f"{prefix}登录异常, 错误原因: {e}"
            print(msg)
            global_sign_results.append(msg + "\n")
            return

        if not isinstance(userInfo, dict) or not userInfo.get("token"):
            reason = (userInfo or {}).get("msg", "未知（未拿到 token）") if isinstance(userInfo, dict) else userInfo
            msg = f"{prefix}登录失败, 错误原因: {reason}"
            print(msg)
            global_sign_results.append(msg + "\n")
            return

        userId = userInfo["userId"]
        token = userInfo["token"]
        sign_info = create_sign(userId + "student")
        planId = get_plan_id(user_info, token, sign_info)

        # 今日是否已有记录：True=已打 / False=未打 / None=查询失败
        # 查询失败时按「已打」处理是危险的（会漏卡），按「未打」处理也危险（会重复）。
        # 这里选择放弃本次、等下次触发，因为一天有多次机会，宁可漏一次也不重复。
        already = check_sign(token, DAILY_SIGN_TYPE, user_info)
        if already is None and not RepeatCheckIn:
            msg = f"{prefix}今日打卡状态未知（查询接口异常），本次跳过，等待下次触发"
            print(msg + "\n")
            global_sign_results.append(msg + "\n")
            return

        # 额外确认：只要今天已存在任意类型记录就跳过，保证「一天一条」
        if already and not RepeatCheckIn:
            print(f"{prefix}今日已有打卡记录, 任务跳过。\n")
            global_sign_results.append(f"{prefix}今日已有记录，跳过\n")
            return

        print(f"{prefix}准备打卡\n")
        try:
            signResp, msg, full_response = save_user_info(
                user_info,
                userId,
                token,
                planId,
                user_info["province"],
                user_info["address"],
                signType=DAILY_SIGN_TYPE,
                latitude=user_info["latitude"],
                longitude=user_info["longitude"],
            )
        except Exception as e:
            err = f"{prefix}打卡失败, 错误原因: {e}"
            print(err + "\n")
            global_sign_results.append(err + "\n")
            return

        dprint(f"{prefix}打卡响应: {full_response}\n")

        # 隐私加固：原版此处会把「手机号 + 打卡类型 + 结果」以明文 HTTP POST 到
        # 作者自建的统计服务器（阿里云北京 IP）。已整段移除。
        ok = "成功！" if signResp else "失败！"
        global_sign_results.append(f"{prefix}工学云打卡{ok}\n")

    finally:
        timer.cancel()
