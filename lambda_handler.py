import os
import sys

# Add the app directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mangum import Mangum

from app.main import app

# Create Mangum handler
handler = Mangum(app, lifespan="off")

