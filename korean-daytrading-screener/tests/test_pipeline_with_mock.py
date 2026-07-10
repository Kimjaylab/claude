from screener.brokers.mock_client import MockClient
from screener.config import load_screening_rules, load_settings
from screener.data.universe import UniverseFilter
from screener.notify.telegram_bot import format_daily_report
from screener.pipeline import run_pipeline


def test_pipeline_runs_end_to_end_with_mock_broker(tmp_path, monkeypatch):
    # 프로젝트 데이터 캐시 경로를 임시 디렉터리로 돌려 실제 data/ 폴더를 건드리지 않는다.
    import screener.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "PROJECT_ROOT", tmp_path)
    # 종목마스터 다운로드는 실제 외부망 호출이라 테스트에서는 건너뛰고
    # is_investable()의 이름 기반 폴백만으로 검증한다.
    monkeypatch.setattr(UniverseFilter, "load", lambda self, force_refresh=False: None)

    broker = MockClient(seed=1)
    settings = load_settings()
    rules = load_screening_rules()

    candidates, regime_note = run_pipeline(broker, dart_client=None, settings=settings, rules=rules)

    assert isinstance(candidates, list)
    for c in candidates:
        assert 0 <= c.final_score
        assert c.risk.stop_loss <= c.risk.entry_price

    report = format_daily_report(candidates, regime_note)
    assert "단타 후보" in report
