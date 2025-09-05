# routes/books.py
import logging
from typing import List, Literal, Optional
from uuid import uuid4

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, status

from models.database import get_db
from models.database_models import Book as BookModel
from models.schemas import Book, BookResponse, BookUpdate, SuccessResponse
from services.auth_service import auth_service, TokenData

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Books"], prefix="/books")

@router.post(
    "",
    response_model=BookResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new book",
)
async def create_book(
    book: Book, 
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Create a new book in the database"""
    book_id = uuid4().hex

    try:
        # Create book using SQLAlchemy
        db_book = BookModel(
            book_id=book_id,
            name=book.name,
            genre=book.genre,
            price=book.price
        )
        
        db.add(db_book)
        await db.commit()
        await db.refresh(db_book)

        logger.info(f"Book created: {book_id} - {book.name}")
        return BookResponse(
            book_id=db_book.book_id,
            name=db_book.name,
            genre=db_book.genre,
            price=float(db_book.price),
            created_at=db_book.created_at.isoformat(),
            updated_at=db_book.updated_at.isoformat(),
        )

    except Exception as e:
        logger.error(f"Book creation failed: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create book",
        )

@router.get(
    "",
    response_model=List[BookResponse],
    summary="Get all books",
)
async def list_books(
    genre: Optional[Literal["fiction", "non-fiction"]] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Get all books with optional filtering and pagination"""
    try:
        query = select(BookModel)
        
        if genre:
            query = query.where(BookModel.genre == genre)
            
        query = query.order_by(BookModel.created_at.desc()).offset(offset).limit(limit)
        
        result = await db.execute(query)
        books = result.scalars().all()

        return [
            BookResponse(
                book_id=book.book_id,
                name=book.name,
                genre=book.genre,
                price=float(book.price),
                created_at=book.created_at.isoformat(),
                updated_at=book.updated_at.isoformat(),
            )
            for book in books
        ]

    except Exception as e:
        logger.error(f"Failed to fetch books: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch books",
        )

@router.get(
    "/{book_id}",
    response_model=BookResponse,
    summary="Get a book by ID",
)
async def get_book_by_id(
    book_id: str, 
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Get a specific book by ID"""
    try:
        result = await db.execute(
            select(BookModel).where(BookModel.book_id == book_id)
        )
        book = result.scalar_one_or_none()

        if not book:
            logger.warning(f"Book not found: {book_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book with id {book_id} not found",
            )

        return BookResponse(
            book_id=book.book_id,
            name=book.name,
            genre=book.genre,
            price=float(book.price),
            created_at=book.created_at.isoformat(),
            updated_at=book.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch book {book_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch book",
        )

@router.put(
    "/{book_id}",
    response_model=BookResponse,
    summary="Update a book",
)
async def update_book(
    book_id: str, 
    book_update: BookUpdate, 
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Update a specific book"""
    try:
        # First get the book
        result = await db.execute(
            select(BookModel).where(BookModel.book_id == book_id)
        )
        book = result.scalar_one_or_none()
        
        if not book:
            logger.warning(f"Book not found for update: {book_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book with id {book_id} not found",
            )

        # Prepare update data
        update_data = {}
        if book_update.name is not None:
            update_data["name"] = book_update.name
        if book_update.genre is not None:
            update_data["genre"] = book_update.genre
        if book_update.price is not None:
            update_data["price"] = book_update.price

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update",
            )

        # Update the book
        await db.execute(
            update(BookModel)
            .where(BookModel.book_id == book_id)
            .values(**update_data)
        )
        await db.commit()
        
        # Refresh to get updated values
        await db.refresh(book)
        
        logger.info(f"Book updated: {book_id}")
        return BookResponse(
            book_id=book.book_id,
            name=book.name,
            genre=book.genre,
            price=float(book.price),
            created_at=book.created_at.isoformat(),
            updated_at=book.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update book {book_id}: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update book",
        )

@router.delete(
    "/{book_id}",
    response_model=SuccessResponse,
    summary="Delete a book",
)
async def delete_book(
    book_id: str, 
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Delete a specific book"""
    try:
        result = await db.execute(
            select(BookModel).where(BookModel.book_id == book_id)
        )
        book = result.scalar_one_or_none()
        
        if not book:
            logger.warning(f"Book not found for deletion: {book_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book with id {book_id} not found",
            )

        await db.delete(book)
        await db.commit()

        logger.info(f"Book deleted: {book_id}")
        return SuccessResponse(
            message=f"Book with id {book_id} deleted successfully",
            status_code=200,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete book {book_id}: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete book",
        )

@router.get(
    "/random-book",
    response_model=BookResponse,
    summary="Get a random book",
)
async def get_random_book(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Get a random book from the database"""
    try:
        result = await db.execute(
            select(BookModel).order_by(func.random()).limit(1)
        )
        book = result.scalar_one_or_none()

        if not book:
            logger.warning("No books found for random selection")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No books found in database",
            )

        return BookResponse(
            book_id=book.book_id,
            name=book.name,
            genre=book.genre,
            price=float(book.price),
            created_at=book.created_at.isoformat(),
            updated_at=book.updated_at.isoformat(),
        )

    except Exception as e:
        logger.error(f"Failed to fetch random book: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch random book",
        )

@router.get(
    "/stats/summary",
    response_model=dict,
    summary="Get books statistics",
)
async def get_books_stats(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Get statistics about books in the database"""
    try:
        # Use SQLAlchemy's func for aggregation
        total_books = await db.scalar(select(func.count(BookModel.book_id)))
        fiction_count = await db.scalar(
            select(func.count(BookModel.book_id)).where(BookModel.genre == 'fiction')
        )
        non_fiction_count = await db.scalar(
            select(func.count(BookModel.book_id)).where(BookModel.genre == 'non-fiction')
        )
        avg_price = await db.scalar(select(func.avg(BookModel.price)))
        min_price = await db.scalar(select(func.min(BookModel.price)))
        max_price = await db.scalar(select(func.max(BookModel.price)))

        return {
            "total_books": total_books or 0,
            "fiction_count": fiction_count or 0,
            "non_fiction_count": non_fiction_count or 0,
            "average_price": float(avg_price) if avg_price else 0,
            "min_price": float(min_price) if min_price else 0,
            "max_price": float(max_price) if max_price else 0,
        }

    except Exception as e:
        logger.error(f"Failed to fetch statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch statistics",
        )