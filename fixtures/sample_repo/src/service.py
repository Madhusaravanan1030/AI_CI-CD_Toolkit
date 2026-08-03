from src.math_utils import add

def compute_total(items):
    total = 0
    for item in items:
        total = add(total, item)
    return total
