# 必须在导入任何网络库之前打补丁：api.moguding.net 会返回 6to4 IPv6 地址，
# 在 GitHub Actions 等环境里 IPv6 不可达，而 Python 默认优先连 IPv6 且不自动
# 回退 IPv4，导致 "Network is unreachable"（curl 没事是因为它有 Happy Eyeballs）。
from modules.net_patch import force_ipv4
force_ipv4()

from modules.load_config import load_config, dprint
from modules.send_sign_in_threading import send_sign_in_threading

# ❗部署时确保这里是False，敏感信息输出开关, 例如用户名和手机号还有部分接口响应内容。
dprint.DEBUG = False


def handler(event, context):
    users = load_config()
    send_sign_in_threading(users)


# ❗1. 开发环境时解除下方的handler(0, 0)用于启动主程序
# ❗2. Github云函数需要保留这一行
# ❗3. 华为云函数需要注释这一行, 否则会连续运行2次打卡任务, 但目前华为云没有opencv-python包, 还是先不支持了
handler(0, 0)
