"""供 IDE 单进程断点调试使用的 FastAPI 启动入口。

该入口直接把 FastAPI app 对象交给 Uvicorn，并且刻意不启用 reload 或多个 worker。
这样请求处理始终发生在调试器启动的当前 Python 进程中，PyCharm/VS Code 的断点可以
稳定命中。日常自动重载或生产部署仍应使用命令行 Uvicorn 配置。
"""

import asyncio

import uvicorn

from src.api import app


def main() -> None:
    """在显式事件循环中启动服务器，兼容 PyCharm 2024.3 调试器。

    Uvicorn 0.50 的 `Server.run()` 会向 `asyncio.run()` 传递 `loop_factory`。
    PyCharm 2024.3 调试器替换的旧版函数不接受该参数，因此这里直接等待
    `Server.serve()`，绕过冲突入口，同时仍保留 Uvicorn 的完整服务器行为。
    """
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="debug",
    )
    server = uvicorn.Server(config)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(server.serve())
    finally:
        # 显式清理事件循环，防止 IDE 多次 Debug 时复用已经关闭的循环。
        loop.close()
        asyncio.set_event_loop(None)


if __name__ == "__main__":
    main()
