import logging
import sys
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
tenant_id_ctx: ContextVar[str] = ContextVar("tenant_id", default="-")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        record.tenant_id = tenant_id_ctx.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [request_id=%(request_id)s tenant_id=%(tenant_id)s] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
