import functools

def audit_logger(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        return result
    return wrapper

@audit_logger
def execute_trade(account_id, amount):
    fee = amount * 0.002
    return amount - fee
