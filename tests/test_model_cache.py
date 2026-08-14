from engine.lyrics import drop_model_cache, get_cached_model, release_cuda


def test_get_cached_model_reuses_same_object(monkeypatch):
    loads: list[tuple] = []

    class FakeWhisper:
        def __init__(self, name, device):
            self.name = name
            self.device = device

    def fake_load(name, device="cpu"):
        loads.append(("whisper", name, device))
        return FakeWhisper(name, device)

    import types
    import sys

    fake = types.SimpleNamespace(load_model=fake_load)
    monkeypatch.setitem(sys.modules, "whisper", fake)
    drop_model_cache()

    a = get_cached_model("small", "cpu", kind="whisper")
    b = get_cached_model("small", "cpu", kind="whisper")
    assert a is b
    assert loads == [("whisper", "small", "cpu")]


def test_get_cached_model_reloads_on_name_change(monkeypatch):
    loads: list[tuple] = []

    class FakeWhisper:
        def __init__(self, name, device):
            self.name = name

    def fake_load(name, device="cpu"):
        loads.append(("whisper", name, device))
        return FakeWhisper(name, device)

    import types
    import sys

    monkeypatch.setitem(sys.modules, "whisper", types.SimpleNamespace(load_model=fake_load))
    drop_model_cache()

    a = get_cached_model("small", "cpu", kind="whisper")
    b = get_cached_model("large-v3", "cpu", kind="whisper")
    assert a is not b
    assert b.name == "large-v3"
    assert loads == [("whisper", "small", "cpu"), ("whisper", "large-v3", "cpu")]


def test_drop_and_release_force_reload(monkeypatch):
    loads: list[tuple] = []

    class FakeWhisper:
        pass

    def fake_load(name, device="cpu"):
        loads.append((name, device))
        return FakeWhisper()

    import types
    import sys

    monkeypatch.setitem(sys.modules, "whisper", types.SimpleNamespace(load_model=fake_load))
    drop_model_cache()

    get_cached_model("small", "cpu", kind="whisper")
    drop_model_cache()
    get_cached_model("small", "cpu", kind="whisper")
    release_cuda()
    get_cached_model("small", "cpu", kind="whisper")
    assert len(loads) == 3


def test_kind_isolation_whisper_vs_stable(monkeypatch):
    loads: list[tuple] = []

    class Fake:
        def __init__(self, kind, name):
            self.kind = kind
            self.name = name

    def whisper_load(name, device="cpu"):
        loads.append(("whisper", name))
        return Fake("whisper", name)

    def stable_load(name, device="cpu"):
        loads.append(("stable", name))
        return Fake("stable", name)

    import types
    import sys

    monkeypatch.setitem(sys.modules, "whisper", types.SimpleNamespace(load_model=whisper_load))
    monkeypatch.setitem(sys.modules, "stable_whisper", types.SimpleNamespace(load_model=stable_load))
    drop_model_cache()

    w = get_cached_model("small", "cpu", kind="whisper")
    s = get_cached_model("small", "cpu", kind="stable")
    assert w is not s
    assert w.kind == "whisper"
    assert s.kind == "stable"
    assert loads == [("whisper", "small"), ("stable", "small")]
