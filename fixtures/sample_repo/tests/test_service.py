from src.service import compute_total

def test_compute_total():
    assert compute_total([1, 2, 3]) == 6
