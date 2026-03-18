from utils.batching import FixedSizeBatchStrategy


def test_split_returns_5_sized_batches() -> None:
    items = list(range(13))
    strategy = FixedSizeBatchStrategy(batch_size=5)
    batches = strategy.split(items)
    assert len(batches) == 3
    assert len(batches[0]) == 5
    assert len(batches[1]) == 5
    assert len(batches[2]) == 3
