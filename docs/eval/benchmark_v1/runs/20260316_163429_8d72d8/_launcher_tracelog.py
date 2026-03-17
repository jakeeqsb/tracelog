import sys, os, logging, importlib.util
sys.path.insert(0, '/Users/jake/Desktop/SunbumDesktopMacBookAir/Workspace/tracelog')

from tracelog import FileExporter, TraceLogHandler, get_buffer, trace
from tracelog.context import ContextManager

def _reset():
    ctx = ContextManager()
    ctx._trace_id.set("")
    ctx._span_id.set("")
    ctx._parent_span_id.set("")
    ctx._depth.set(0)
    try:
        get_buffer().clear()
    except Exception:
        pass

_reset()

spec = importlib.util.spec_from_file_location("scenario", 'docs/eval/benchmark/runs/20260316_163429_8d72d8/scenario_code.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
Scenario = mod.Scenario

logger = logging.getLogger("tracelog.bench")
logger.setLevel(logging.DEBUG)
logger.handlers = []
logger.propagate = False

if True:
    handler = TraceLogHandler(exporter=FileExporter('docs/eval/benchmark/runs/20260316_163429_8d72d8/raw_tracelog.log'), capacity=2000, max_chunks=200)
else:
    handler = logging.FileHandler('docs/eval/benchmark/runs/20260316_163429_8d72d8/raw_tracelog.log', mode="w")
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(threadName)s] %(levelname)s - %(message)s"))

logger.addHandler(handler)
try:
    scenario = Scenario(logger)
    scenario.run()
except Exception:
    logger.exception("scenario execution failed")
finally:
    for h in list(logger.handlers):
        h.flush(); h.close(); logger.removeHandler(h)
