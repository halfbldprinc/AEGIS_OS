from aegis.cli import build_parser, main


def test_build_parser_defaults():
    parser = build_parser()
    args = parser.parse_args(["daemon", "--iterations", "2"])

    assert args.command == "daemon"
    assert args.iterations == 2


def test_main_daemon_run(monkeypatch):
    called = {"cycle": 0}

    class DummyDaemon:
        def run_cycle(self):
            called["cycle"] += 1

    monkeypatch.setattr("aegis.cli.AegisDaemon", lambda: DummyDaemon())

    main(["daemon", "--iterations", "3"])
    assert called["cycle"] == 3


def test_build_parser_ops_soak():
    parser = build_parser()
    args = parser.parse_args(["ops", "soak", "--cycles", "5", "--sleep", "0.0"])

    assert args.command == "ops"
    assert args.ops_command == "soak"
    assert args.cycles == 5


def test_main_ops_chaos(monkeypatch):
    class DummyDaemon:
        def run_chaos_scenario(self, scenario):
            return {"scenario": scenario, "status": "recovered"}

    monkeypatch.setattr("aegis.cli.AegisDaemon", lambda: DummyDaemon())
    main(["ops", "chaos", "--scenario", "voice_interrupt"])
