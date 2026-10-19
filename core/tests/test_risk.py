"""Risk-scorecard: чистые функции весов и бакетов (doc 08 §1, холодный старт M5)."""

from polylog.risk.scorecard import AccountFeatures, scorecard


def test_scorecard_all_green_is_low():
    f = AccountFeatures(days_silence=1, unanswered_ratio=0.0,
                        unhandled_ratio=0.0, avg_score=80, chain_depth=3)
    r = scorecard(f)
    assert r["band"] == "low"
    assert r["score"] == 0.0
    assert all(fa["contribution"] == 0 for fa in r["factors"])


def test_scorecard_silent_high_risk():
    f = AccountFeatures(days_silence=30, unanswered_ratio=0.6,
                        unhandled_ratio=0.8, avg_score=20, chain_depth=5)
    r = scorecard(f)
    assert r["band"] == "high"
    assert r["score"] >= 60
    # доминирующий фактор — тишина (наибольший вклад)
    assert r["factors"][0]["feature"] == "days_silence"
    assert r["factors"][0]["description"].startswith("тишина 30")


def test_scorecard_no_scores_penalty():
    f = AccountFeatures(avg_score=None)
    r = scorecard(f)
    fa = next(x for x in r["factors"] if x["feature"] == "avg_score")
    assert fa["contribution"] == 10.0 and "не обработаны" in fa["description"]


def test_scorecard_factors_sorted_by_contribution():
    f = AccountFeatures(days_silence=5, unanswered_ratio=0.3,
                        unhandled_ratio=0.1, avg_score=70)
    r = scorecard(f)
    contribs = [fa["contribution"] for fa in r["factors"]]
    assert contribs == sorted(contribs, reverse=True)
    assert 25 <= r["score"] < 55  # medium (пороги scorecard 25/55)


def test_scorecard_has_model_id():
    r = scorecard(AccountFeatures())
    assert r["model_id"].startswith("scorecard@")
    assert r["calibrated"] is False
