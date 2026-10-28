def generate_lookup(categories, values):
    lookup_map = {cat: val * 10 for cat, val in zip(categories, values)}
    filtered_evens = [v for v in lookup_map.values() if v % 2 == 0]
    unique_lengths = {len(cat) for cat in lookup_map.keys()}
    return lookup_map, filtered_evens, unique_lengths
