from fastapi import status
from loguru import logger


async def get_current_user_websocket(token: str):
    """Get current user from WebSocket token - handles tuple returns from services"""
    try:
        if not token or not token.strip():
            logger.error("No token provided")
            return None

        logger.debug(f"Authenticating WebSocket with token: {token[:20]}...")
        
        # Import inside function to avoid circular imports
        from app.database import get_db_context
        from app.services.auth_service import auth_service
        from app.services.user_service import user_service

        # Step 1: Verify token
        token_result = await auth_service.verify_token(token)
        logger.debug(f"Token verification result type: {type(token_result)}")
        
        # Handle different return patterns from auth_service.verify_token
        user_id = None
        
        if isinstance(token_result, tuple):
            # Pattern: (data, status_code) 
            if len(token_result) == 2:
                data, status_code = token_result
                logger.debug(f"Token verification status: {status_code}")
                
                if status_code == status.HTTP_200_OK:
                    if isinstance(data, dict):
                        user_id = data.get("user_id")
                    elif hasattr(data, 'user_id'):
                        user_id = data.user_id
                    elif hasattr(data, 'get'):
                        user_id = data.get('user_id')
                else:
                    logger.error(f"Token verification failed with status: {status_code}")
                    return None
            else:
                logger.error(f"Unexpected tuple length from verify_token: {len(token_result)}")
                return None
                
        elif isinstance(token_result, dict):
            # Pattern: Direct dictionary
            user_id = token_result.get("user_id")
            
        elif hasattr(token_result, 'user_id'):
            # Pattern: User object directly
            user_id = token_result.user_id
            
        else:
            logger.error(f"Unexpected token result type: {type(token_result)}")
            return None
        
        # Validate user_id
        if not user_id:
            logger.error("No user_id extracted from token verification")
            return None
            
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            logger.error(f"Invalid user_id format: {user_id}")
            return None
        
        logger.debug(f"Extracted user_id: {user_id}")
        
        # Step 2: Get user from database - handle tuple return from user_service
        async with get_db_context() as db:
            user_result = await user_service.get_user_by_id(user_id, db)
            
            # Handle tuple return (data, status_code)
            if isinstance(user_result, tuple) and len(user_result) == 2:
                user_data, status_code = user_result
                if status_code != status.HTTP_200_OK or not user_data:
                    logger.error(f"User service returned error: {status_code}")
                    return None
                
                # Convert dict to a simple object for attribute access
                if isinstance(user_data, dict):
                    class SimpleUser:
                        def __init__(self, data):
                            for key, value in data.items():
                                setattr(self, key, value)
                            # Ensure we have user_id attribute for compatibility
                            if hasattr(self, 'id') and not hasattr(self, 'user_id'):
                                setattr(self, 'user_id', self.id)
                    
                    user_obj = SimpleUser(user_data)
                    logger.info(f"WebSocket authentication successful for user: {user_obj.user_id}")
                    return user_obj
                else:
                    # If it's already an object, return it directly
                    logger.info(f"WebSocket authentication successful for user: {user_data.user_id}")
                    return user_data
            else:
                # If it's not a tuple, assume it's the user object directly
                logger.info(f"WebSocket authentication successful for user: {user_result.user_id}")
                return user_result
            
    except Exception as e:
        logger.error(f"WebSocket authentication error: {str(e)}")
        import traceback
        logger.debug(f"Authentication traceback: {traceback.format_exc()}")
        return None
    
        