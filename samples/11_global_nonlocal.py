GLOBAL_DISPATCH_COUNT = 0

def manage_state(initial_seed):
    state_holder = {"seed": initial_seed}

    def increment():
        nonlocal state_holder
        global GLOBAL_DISPATCH_COUNT
        GLOBAL_DISPATCH_COUNT += 1
        state_holder["seed"] += 5
        return state_holder["seed"]

    return increment
