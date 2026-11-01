#!/usr/bin/env python3
"""
Production entry point for API Tools service
"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from src.api import app
from src.utils.storage import storage_path

VERSION = "0.5.2"

def main():
    """Main entry point"""
    print(f"Starting API Tools service v{VERSION}")
    print(f"Environment: {'Development' if os.getenv('FLASK_DEBUG', 'False').lower() == 'true' else 'Production'}")
    print(f"Storage path: {storage_path()}")
    print(f"Working directory: {os.getcwd()}")
    
    # Ensure storage directory exists
    os.makedirs(storage_path(), exist_ok=True)
    
    # Check if running with Gunicorn
    if 'gunicorn' in os.environ.get('SERVER_SOFTWARE', ''):
        print("Running with Gunicorn WSGI server")
        return app
    else:
        # Development mode fallback
        print("WARNING: Running Flask development server. Use Gunicorn for production!")
        app.run(
            host="0.0.0.0", 
            port=int(os.getenv('PORT', 8080)),
            debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
        )

# WSGI callable
application = app

if __name__ == '__main__':
    main()
