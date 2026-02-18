from functools import wraps
import inspect
from typing import Callable, Any
from .core import TraceLog

# We can instantiate a logger here or inside the wrapper. 
# Since TraceLog shares the thread-local buffer, it's cheap to create.
_logger = TraceLog() 

def trace(func: Callable) -> Callable:
    """
    Decorator to trace function execution flow.
    Captures arguments, return values, and exceptions.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # 1. Capture Arguments
        try:
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            arg_str = ", ".join(f"{k}={v!r}" for k, v in bound_args.arguments.items())
        except Exception:
            arg_str = "..." # Fallback if signature binding fails for some C-extensions or complex cases

        func_name = func.__name__
        
        # 2. Log Entry (Increase Depth)
        # Using internal methods or formatted strings.
        # TraceLog doesn't have a 'raw_push' exposed easily, but we can use info/debug
        # Or better, we should add 'call' and 'ret' methods to TraceLog context-aware part.
        
        # For now, let's manually format to match DSL spec
        # DSL: >> func_name(args)
        _logger.buffer.push(f"{'  ' * _logger.context.get_depth()}>> {func_name}({arg_str})")
        _logger.context.increase_depth()

        try:
            # 3. Execute Function
            result = func(*args, **kwargs)
            
            # 4. Log Exit (Decrease Depth)
            _logger.context.decrease_depth()
            # DSL: << result
            _logger.buffer.push(f"{'  ' * _logger.context.get_depth()}<< {result!r}")
            return result

        except Exception as e:
            # 5. Log Exception
            _logger.context.decrease_depth()
            # DSL: !! Exception: msg
            _logger.buffer.push(f"{'  ' * _logger.context.get_depth()}!! {type(e).__name__}: {str(e)}")
            
            # Trigger Dump for unhandled exception (if desired here, usually yes)
            # But maybe we let the top-level error handler dump it?
            # If we re-raise, it bubbles up.
            # If we dump here, we might dump multiple times for nested exceptions.
            # Let's dump here to be safe and ensure context is captured AT THE SOURCE.
            _logger.dump()
            raise e

    return wrapper
