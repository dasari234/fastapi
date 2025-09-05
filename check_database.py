import logging

from database import (check_tables_exist, emergency_create_missing_tables,
                      ensure_db_initialized, force_recreate_tables)

logging.basicConfig(level=logging.INFO)

async def main():
    print("Checking database status...")
    
    try:
        # Initialize database
        pool = await ensure_db_initialized()
        print("Database connection established")
        
        # Check tables
        tables = await check_tables_exist()
        print(f"Tables status: {tables}")
        
        if not tables.get('file_uploads'):
            print("File_uploads table missing! Creating emergency tables...")
            result = await emergency_create_missing_tables()
            print(f"Emergency creation result: {result}")
            
            # Check again
            tables = await check_tables_exist()
            print(f"Tables status after emergency: {tables}")
        
        if tables.get('all_tables_exist'):
            print("All tables are ready!")
        else:
            print("Some tables are still missing")
            response = input("Do you want to force recreate all tables? (y/N): ")
            if response.lower() == 'y':
                print("FORCE RECREATING ALL TABLES (WILL LOSE DATA!)...")
                result = await force_recreate_tables()
                print(f"Force recreate result: {result}")
                
                # Final check
                tables = await check_tables_exist()
                print(f"Final tables status: {tables}")
            
    except Exception as e:
        print(f"Error: {e}")
