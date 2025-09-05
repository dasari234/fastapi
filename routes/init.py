from .auth import router as auth_router
from .books import router as books_router
from .files import router as files_router
from .health import router as health_router
from .root import router as root_router
from .users import router as users_router

__all__ = [
    "root_router", 
    "health_router", 
    "auth_router",
    "users_router",
    "books_router", 
    "files_router"
]