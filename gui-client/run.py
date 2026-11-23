#!/usr/bin/env python3
"""Frida 反检测 PC 客户端 GUI 启动入口。

用法:
    python run.py                     # 默认使用自定义端口 20442(与本项目反检测 frida-server 配套)
    python run.py --port 27042        # 使用官方默认端口
    python run.py --adb /path/to/adb  # 指向 platform-tools 里的 adb 可执行文件
"""
import sys, argparse


def main() -> int:
    ap = argparse.ArgumentParser(description="Frida Companion GUI")
    ap.add_argument("--port", type=int, default=None,
                    help="frida-server 在设备上的控制端口(默认读取配置，本项目配套为 20442)")
    ap.add_argument("--adb", default=None, help="adb 可执行文件绝对路径")
    ap.add_argument("--server-name", default=None,
                    help="设备上 frida-server 二进制文件名(用于自动启动, 默认 frida-server)")
    args = ap.parse_args()

    from companion.core import config
    config.CLI_ARGS = args

    if args.port:
        config.CONTROL_PORT = args.port
    if args.adb:
        config.ADB_PATH = args.adb
    if args.server_name:
        config.SERVER_NAME = args.server_name

    from companion.ui.main_window import run_app
    return run_app()


if __name__ == "__main__":
    sys.exit(main())