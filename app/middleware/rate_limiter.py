from fastapi import HTTPException, Request
from services.redis_service import redis_service
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, time_window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.time_window = time_window

    async def dispatch(self, request: Request, call_next):
        # Get client IP
        client_ip = request.client.host
        endpoint = request.url.path
        
        # Create rate limit key
        key = f"rate_limit:{client_ip}:{endpoint}"
        
        # Get current count
        current = await redis_service.get(key) or 0
        
        if int(current) >= self.max_requests:
            raise HTTPException(
                status_code=429, 
                detail="Rate limit exceeded"
            )
        
        # Increment counter
        await redis_service.increment(key)
        
        # Set expiration if this is the first request
        if current == 0:
            await redis_service.redis.expire(key, self.time_window)
        
        response = await call_next(request)
        return response
    
    