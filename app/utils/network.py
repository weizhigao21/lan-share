"""网络工具：本机局域网 IP 探测。"""
import socket


def get_lan_ip() -> str:
    """获取本机在局域网中的 IP 地址。

    通过 UDP "连接" 一个外部地址来让系统选择出网网卡（UDP connect 不产生真实流量，
    无外网时也能正确返回本机局域网 IP）。

    Returns:
        局域网 IP 字符串；失败时回退为 127.0.0.1。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
