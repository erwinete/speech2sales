"""Greedy-кластеризация возражений (polylog.insights.clustering)."""

from polylog.insights.clustering import cluster_items, cosine


def test_cosine_identical_and_orthogonal():
    assert abs(cosine([1, 0], [1, 0]) - 1.0) < 1e-9
    assert abs(cosine([1, 0], [0, 1])) < 1e-9


def test_two_distinct_clusters():
    items = [
        {"vector": [1.0, 0.0, 0.0], "text": "сколько стоит", "type": "price"},
        {"vector": [0.9, 0.1, 0.0], "text": "какая цена", "type": "price"},
        {"vector": [0.0, 1.0, 0.0], "text": "у нас есть поставщик", "type": "existing_supplier"},
        {"vector": [0.1, 0.9, 0.0], "text": "мы работаем с другим", "type": "existing_supplier"},
    ]
    clusters = cluster_items(items, threshold=0.82)
    assert len(clusters) == 2
    assert len(clusters[0].members) >= 2  # сортировка по размеру
    dominant = [c.as_dict()["dominant_type"] for c in clusters]
    assert set(dominant) == {"price", "existing_supplier"}


def test_single_item_is_own_cluster():
    clusters = cluster_items([{"vector": [1, 2, 3], "text": "x", "type": "other"}])
    assert len(clusters) == 1 and clusters[0].members == [0]


def test_quotes_preserved_in_cluster():
    items = [
        {"vector": [1.0, 0.0], "text": "цена?", "type": "price"},
        {"vector": [0.95, 0.05], "text": "почём?", "type": "price"},
    ]
    c = cluster_items(items)[0]
    d = c.as_dict()
    assert set(d["quotes"]) == {"цена?", "почём?"}
    assert d["top_types"] == [("price", 2)]
