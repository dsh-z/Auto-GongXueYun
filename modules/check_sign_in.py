import requests
from modules.load_config import dprint
from modules.map_headers import header_user_agent
from datetime import datetime, timedelta


# 查用户是否已经打卡
def check_sign(check_sign_token, sign_type, user=None):
    check_sign_url = "https://api.moguding.net:9000/attendence/clock/v2/listSynchro"

    # 获取当天的打卡信息
    search_start_time, search_end_time = get_current_day()
    data = {
        "startTime": search_start_time,
        "endTime": search_end_time,
    }
    # 关键：必须带 roleKey 和 user-agent。
    # 原版只发 Authorization，服务端会返回 code=403
    # 「非法请求，禁止访问:<你的IP>」—— 这句话会把人误导成"IP 被拉黑"，
    # 实测同一 IP 只要补上这两个头就立刻 200 success。
    headers = {
        "Authorization": f"{check_sign_token}",
        "roleKey": "student",
        "content-type": "application/json; charset=UTF-8",
    }
    if user is not None:
        headers["user-agent"] = header_user_agent(user)
    else:
        headers["user-agent"] = "Dart/2.17 (dart:io)"

    response = requests.post(check_sign_url, json=data, headers=headers, timeout=30)
    response_data = response.json()

    if response_data.get("code") != 200:
        # 不要把接口错误当成"没打过卡"，否则会重复提交打卡
        print(f"   查询打卡记录失败: code={response_data.get('code')} "
              f"msg={response_data.get('msg')}")
        return None

    records = response_data.get("data")
    if not isinstance(records, list):
        print(f"   查询返回结构异常，已跳过重复检查: {str(records)[:120]}")
        return None

    # 检查是否有过打卡记录
    for record in records:
        if record.get("type") == sign_type:
            # 打过卡
            return True
    # 没打过卡
    return False


# 获取当前月份起始时间
# 这里的具体时间无所谓，返回的内容是全天的签到记录, 写时间是因为标准的时间格式要求
# def get_current_month():
#     now = datetime.now()
#     start_of_month = datetime(now.year, now.month, 1)
#     if now.month == 12:
#         next_month_start = datetime(now.year + 1, 1, 1)
#     else:
#         next_month_start = datetime(now.year, now.month + 1, 1)
#     end_of_month = next_month_start - timedelta(days=1)
#     month_start_time = start_of_month.strftime("%Y-%m-%d %H:%M:%S")
#     month_end_time = end_of_month.strftime("%Y-%m-%d 00:00:00")
#     return month_start_time, month_end_time


# 获取当天起始时间
def get_current_day():
    now = datetime.now()
    start_of_day = datetime(now.year, now.month, now.day)
    end_of_day = start_of_day + timedelta(days=1, seconds=-1)
    day_start_time = start_of_day.strftime("%Y-%m-%d 00:00:00")
    day_end_time = end_of_day.strftime("%Y-%m-%d 23:59:59")
    return day_start_time, day_end_time


# 开发环境测试环境解除注释
# dprint("\n❗注意：以下输出是check_sign模块的开发环境信息，👇")
# day_start_time, day_end_time = get_current_day()
# dprint("打卡信息查询日期范围:\n", day_start_time, "→", day_end_time)
# check_sign(
#     check_sign_token="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
#     sign_type="START",
# )
