def test_debug_entry_uses_explicit_event_loop(monkeypatch):
    """入口不得调用 Server.run，避免触发 PyCharm 不兼容的 asyncio.run 补丁。"""
    from src import run_api

    events = []

    class FakeConfig:
        def __init__(self, app, **options):
            events.append(("config", app, options))

    class FakeServer:
        def __init__(self, config):
            events.append(("server", config))

        async def serve(self):
            events.append(("serve",))

    class FakeLoop:
        def run_until_complete(self, coroutine):
            events.append(("run_until_complete",))
            try:
                coroutine.send(None)
            except StopIteration:
                # 真正的事件循环会把协程正常返回转换为 run_until_complete 的返回值。
                pass

        def close(self):
            events.append(("close",))

    loop = FakeLoop()
    monkeypatch.setattr(run_api.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(run_api.uvicorn, "Server", FakeServer)
    monkeypatch.setattr(run_api.asyncio, "new_event_loop", lambda: loop)
    monkeypatch.setattr(
        run_api.asyncio,
        "set_event_loop",
        lambda value: events.append(("set_loop", value)),
    )

    run_api.main()

    assert events[0] == ("config", run_api.app, {
        "host": "127.0.0.1",
        "port": 8000,
        "log_level": "debug",
    })
    assert ("run_until_complete",) in events
    assert ("serve",) in events
    assert events[-2:] == [("close",), ("set_loop", None)]
