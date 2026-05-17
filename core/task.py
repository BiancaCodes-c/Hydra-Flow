"""Task decorator and DI placeholder."""

def task(func=None, **kwargs):
    def decorator(f):
        return f
    if func:
        return decorator(func)
    return decorator
