from aegis.memory import MemoryStore


def test_memory_upsert_search_delete(tmp_path):
    db_path = tmp_path / "memory.db"
    store = MemoryStore(db_path=str(db_path))

    entry = store.upsert("Write a note about Python unit tests", metadata={"topic": "test"})
    assert entry.text.startswith("Write a note")

    results = store.search("unit tests")
    assert len(results) >= 1
    assert results[0]["id"] == entry.id

    assert store.delete(entry.id)
    assert store.get(entry.id) is None


def test_memory_scope_filtering(tmp_path):
    db_path = tmp_path / "memory.db"
    store = MemoryStore(db_path=str(db_path))

    short = store.upsert("session reminder draft", scope="short_term")
    long = store.upsert("persistent user preference", scope="long_term")

    short_results = store.search("reminder", scope="short_term")
    long_results = store.search("preference", scope="long_term")

    assert any(item["id"] == short.id for item in short_results)
    assert all(item["scope"] == "short_term" for item in short_results)
    assert any(item["id"] == long.id for item in long_results)
    assert all(item["scope"] == "long_term" for item in long_results)
