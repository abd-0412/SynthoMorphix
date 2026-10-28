def outer_pipeline(factor):
    base_multiplier = factor * 1.5

    def inner_step(value):
        local_adjustment = value + 10
        return local_adjustment * base_multiplier

    return inner_step

def run_calculation(initial_val):
    step_fn = outer_pipeline(2)
    return step_fn(initial_val)
