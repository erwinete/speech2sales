"""Predictive-риск (CatBoost-каркас): фолбэк на scorecard без модели/данных,
feature vector, вклады при наличии модели (catboost пропускается, если не
установлен — тесты должны проходить на любом окружении)."""

from pathlib import Path

from polylog.risk.model import N_MIN_OUTCOMES, feature_vector
from polylog.risk.scorecard import AccountFeatures


def test_feature_vector():
    f = AccountFeatures(days_silence=9, unanswered_ratio=0.5, unhandled_ratio=1.0,
                        avg_score=35.0, chain_depth=3)
    vec = feature_vector(f)
    assert vec == [9.0, 0.5, 1.0, 35.0, 3.0]
    # нет скора — маркерная константа -1
    f2 = AccountFeatures(avg_score=None)
    assert feature_vector(f2)[3] == -1.0


def test_n_min_default():
    assert N_MIN_OUTCOMES == 30


def test_predict_without_model_returns_none(monkeypatch, tmp_path):
    """Нет файла модели → None → вызывающий остаётся на scorecard."""
    from polylog.risk import model as rm

    monkeypatch.setattr(rm, "MODEL_PATH", str(tmp_path / "missing.cbm"))
    assert rm.model_ready() is False
    f = AccountFeatures(days_silence=5)
    assert rm.predict(f) is None


def test_predict_with_model(tmp_path):
    """С обученной моделью: скор 0..100, вклады отсортированы, calibrated=True."""
    from polylog.risk import model as rm

    rows = []
    for i in range(40):
        lost = i % 2
        rows.append(([10.0 * lost + i % 5, 0.9 * lost, 1.0 * lost, 30.0 * lost + 10, i % 7], lost))
    out = tmp_path / "risk.cbm"
    rm.train(rows, out_path=str(out))

    probe = AccountFeatures(days_silence=8, unanswered_ratio=0.9,
                            unhandled_ratio=1.0, avg_score=20.0, chain_depth=5)

    import polylog.risk.model as rm_mod

    original = rm_mod.MODEL_PATH
    rm_mod.MODEL_PATH = str(out)
    try:
        assert rm_mod.model_ready() is True
        res = rm_mod.predict(probe)
    finally:
        rm_mod.MODEL_PATH = original
    assert res is not None
    assert 0 <= res["score"] <= 100
    assert res["band"] in ("low", "medium", "high")
    assert res["calibrated"] is True
    assert len(res["factors"]) == 5
    contributions = [f_["contribution"] for f_ in res["factors"]]
    assert contributions == sorted(contributions, reverse=True)
    assert Path(out).is_file()


def test_train_rejects_small_sample(tmp_path):
    try:
        import catboost  # noqa: F401
    except ImportError:
        return
    from polylog.risk import model as rm

    try:
        rm.train([([1.0] * 5, 1)] * 5, out_path=str(tmp_path / "x.cbm"))
        raised = False
    except ValueError:
        raised = True
    assert raised
