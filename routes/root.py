from fastapi import APIRouter

from config import ENVIRONMENT
from schemas import SuccessResponse

router = APIRouter(tags=["Root"])

@router.get(
    "/",
    response_model=SuccessResponse,
    summary="API Root",
)
async def root():
    return SuccessResponse(
        message="Welcome to my bookstore app!",
        status_code=200,
        data={
            "database": "NeonDB (Serverless PostgreSQL)",
            "features": ["CRUD Operations", "Connection Pooling", "Auto-scaling"],
            "environment": ENVIRONMENT,
            "version": "2.0.0",
        },
    )
