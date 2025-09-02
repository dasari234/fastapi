from .books import router as books_router
from .files import router as files_router
from .health import router as health_router
from .root import router as root_router

__all__ = ["root_router", "health_router", "books_router", "files_router"]
