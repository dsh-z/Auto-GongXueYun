import re
import time
import requests

from modules.load_config import dprint

# ---------------------------------------------------------------------------
# ntfy 推送适配层（替换原 pushplus 实现）
#
# 为什么不能照搬原版把中文塞进 Title 头：
#   HTTP header 只允许 latin-1，requests 会对非 ASCII 头值抛
#   UnicodeEncodeError('latin-1' codec can't encode characters)。实测必崩，
#   且崩在 threading 层的 try 里，表现是「卡打成功但推送永远失败」。
#   所以：标题用 ASCII 摘要，所有中文放进 Body。
#
# user.json 的 pushKey 现在填「ntfy 主题名」；留空 = 不推送（打卡不受影响）。
# ---------------------------------------------------------------------------

NTFY_BASE = "https://ntfy.sh"


# 保持原函数名，这样 send_sign_in_threading.py 的 import 不用改。
def push_to_pushplus(users, title, content, topic):
    topic = str(topic or "").strip()
    if not topic:
        # 未配置推送：静默返回，绝不能抛异常影响打卡主流程
        return

    # 公共 ntfy 服务器上短主题名极易与他人的重名，发过去等于把打卡记录送给
    # 陌生人，所以长度和字符集都做下限约束。
    if len(topic) < 8 or not re.fullmatch(r"[A-Za-z0-9_-]+", topic):
        print("X 推送已跳过：pushKey 不像合法的 ntfy 主题名（需 >=8 位字母/数字/-/_）")
        dprint("   生成方法：PowerShell 运行  "
               "-join ((48..57)+(97..122) | Get-Random -Count 24 | ForEach-Object {[char]$_})")
        return

    # 把汇总里的 [成功数/总数] 提到标题，通知栏一眼看出是不是全军覆没
    m = re.search(r"\[\s*\d+\s*/\s*\d+\s*\]", title or "")
    summary = (" " + m.group(0)) if m else ""

    body = f"{title}\n\n{content}".strip()
    bad = any(k in body for k in ("失败", "超时", "验证码", "异常", "错误原因"))

    headers = {
        "Title": f"GXY {'FAIL' if bad else 'OK'}{summary}",
        "Tags": "warning" if bad else "white_check_mark",
        "Priority": "high" if bad else "3",
    }

    # Header 必须全部 latin-1 安全，提前自检，避免线上才炸
    for key, val in headers.items():
        try:
            val.encode("latin-1")
        except UnicodeEncodeError:
            dprint(f"❗推送标题含非 ASCII 字符，已降级: {val!r}")
            headers[key] = "GXY notification"

    ok = False
    for attempt in range(2):          # 一次重试即可，推送失败不该拖慢定时任务
        try:
            resp = requests.post(
                f"{NTFY_BASE}/{topic}",
                data=body.encode("utf-8"),
                headers=headers,
                timeout=15,
            )
            ok = resp.status_code == 200
            if ok:
                break
            dprint(f"推送第 {attempt + 1} 次未成功: {resp.status_code} {resp.text[:200]}")
        except Exception as exc:       # 推送异常绝不影响打卡
            dprint(f"推送第 {attempt + 1} 次异常: {exc}")
        if attempt == 0:
            time.sleep(3)

    for user in users:
        dprint(f'[{user.get("remark", "")}/{user["phone"]}]', end="")
        print("√ 推送成功！" if ok else "X 推送失败（不影响打卡结果）")
