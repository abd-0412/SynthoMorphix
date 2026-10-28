def inspect_object_dynamically(target_obj, prop_name):
    # Dynamic reflection construct: getattr usage triggers policy flag
    if hasattr(target_obj, prop_name):
        return getattr(target_obj, prop_name)
    return None

def evaluate_custom_formula(formula_str, context):
    return eval(formula_str, {}, context)
