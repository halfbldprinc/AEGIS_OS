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
