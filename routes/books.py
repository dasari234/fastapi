import logging
from typing import List, Literal, Optional
from uuid import uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

from models.database import get_db
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
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Create a new book in the database"""
    book_id = uuid4().hex

    try:
        await conn.execute(
            "INSERT INTO books (book_id, name, genre, price) VALUES ($1, $2, $3, $4)",
            book_id,
            book.name,
            book.genre,
            book.price,
        )

        row = await conn.fetchrow(
            "SELECT book_id, name, genre, price, created_at, updated_at FROM books WHERE book_id = $1",
            book_id,
        )

        logger.info(f"Book created: {book_id} - {book.name}")
        return BookResponse(
            book_id=row["book_id"],
            name=row["name"],
            genre=row["genre"],
            price=float(row["price"]),
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        )

    except asyncpg.UniqueViolationError:
        logger.warning(f"Book creation failed - duplicate ID: {book_id}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Book with this ID already exists",
        )
    except Exception as e:
        logger.error(f"Book creation failed: {e}")
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
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Get all books with optional filtering and pagination"""
    try:
        if genre:
            rows = await conn.fetch(
                "SELECT book_id, name, genre, price, created_at, updated_at FROM books WHERE genre = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                genre,
                limit,
                offset,
            )
        else:
            rows = await conn.fetch(
                "SELECT book_id, name, genre, price, created_at, updated_at FROM books ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                limit,
                offset,
            )

        return [
            BookResponse(
                book_id=row["book_id"],
                name=row["name"],
                genre=row["genre"],
                price=float(row["price"]),
                created_at=row["created_at"].isoformat(),
                updated_at=row["updated_at"].isoformat(),
            )
            for row in rows
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
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Get a specific book by ID"""
    try:
        row = await conn.fetchrow(
            "SELECT book_id, name, genre, price, created_at, updated_at FROM books WHERE book_id = $1",
            book_id,
        )

        if not row:
            logger.warning(f"Book not found: {book_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book with id {book_id} not found",
            )

        return BookResponse(
            book_id=row["book_id"],
            name=row["name"],
            genre=row["genre"],
            price=float(row["price"]),
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
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
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Update a specific book"""
    try:
        existing = await conn.fetchrow(
            "SELECT 1 FROM books WHERE book_id = $1", book_id
        )
        if not existing:
            logger.warning(f"Book not found for update: {book_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book with id {book_id} not found",
            )

        update_fields = []
        values = []
        param_count = 1

        if book_update.name is not None:
            update_fields.append(f"name = ${param_count}")
            values.append(book_update.name)
            param_count += 1

        if book_update.genre is not None:
            update_fields.append(f"genre = ${param_count}")
            values.append(book_update.genre)
            param_count += 1

        if book_update.price is not None:
            update_fields.append(f"price = ${param_count}")
            values.append(book_update.price)
            param_count += 1

        if not update_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update",
            )

        values.append(book_id)

        query = f"UPDATE books SET {', '.join(update_fields)} WHERE book_id = ${param_count} RETURNING book_id, name, genre, price, created_at, updated_at"

        row = await conn.fetchrow(query, *values)
        logger.info(f"Book updated: {book_id}")

        return BookResponse(
            book_id=row["book_id"],
            name=row["name"],
            genre=row["genre"],
            price=float(row["price"]),
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update book {book_id}: {e}")
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
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Delete a specific book"""
    try:
        result = await conn.execute("DELETE FROM books WHERE book_id = $1", book_id)

        if result == "DELETE 0":
            logger.warning(f"Book not found for deletion: {book_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Book with id {book_id} not found",
            )

        logger.info(f"Book deleted: {book_id}")
        return SuccessResponse(
            message=f"Book with id {book_id} deleted successfully",
            status_code=200,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete book {book_id}: {e}")
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
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Get a random book from the database"""
    try:
        row = await conn.fetchrow(
            "SELECT book_id, name, genre, price, created_at, updated_at FROM books ORDER BY RANDOM() LIMIT 1"
        )

        if not row:
            logger.warning("No books found for random selection")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No books found in database",
            )

        return BookResponse(
            book_id=row["book_id"],
            name=row["name"],
            genre=row["genre"],
            price=float(row["price"]),
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
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
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(auth_service.get_current_user)
):
    """Get statistics about books in the database"""
    try:
        stats = await conn.fetchrow("""
            SELECT 
                COUNT(*) as total_books,
                COUNT(CASE WHEN genre = 'fiction' THEN 1 END) as fiction_count,
                COUNT(CASE WHEN genre = 'non-fiction' THEN 1 END) as non_fiction_count,
                AVG(price) as average_price,
                MIN(price) as min_price,
                MAX(price) as max_price
            FROM books
        """)

        return {
            "total_books": stats["total_books"],
            "fiction_count": stats["fiction_count"],
            "non_fiction_count": stats["non_fiction_count"],
            "average_price": float(stats["average_price"]) if stats["average_price"] else 0,
            "min_price": float(stats["min_price"]) if stats["min_price"] else 0,
            "max_price": float(stats["max_price"]) if stats["max_price"] else 0,
        }

    except Exception as e:
        logger.error(f"Failed to fetch statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch statistics",
        )