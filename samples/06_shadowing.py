CONFIG_LIMIT = 5000

def compute_tier_a():
    temp_val = 10
    total = temp_val * 2
    if total < CONFIG_LIMIT:
        return total
    return CONFIG_LIMIT

def compute_tier_b():
    temp_val = 20
    total = temp_val * 3
    if total < CONFIG_LIMIT:
        return total
    return CONFIG_LIMIT
