def sort_transactions(transactions):
    key_extractor = lambda item: item.get("priority", 0)
    sorted_items = sorted(transactions, key=key_extractor, reverse=True)
    return sorted_items

def apply_discount(prices, discount_pct):
    calc = lambda p: p * (1 - discount_pct)
    return [calc(price) for price in prices]
