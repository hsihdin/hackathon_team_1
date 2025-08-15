import psycopg
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'dbname': os.getenv('DB_NAME', 'hackathon'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'password'),
    'port': os.getenv('DB_PORT', '5432'),
    'sslmode': os.getenv('DB_SSLMODE', 'prefer')
}

def get_db_connection():
    """Create and return a database connection"""
    try:
        # Build connection string for psycopg3
        conn_string = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}?sslmode={DB_CONFIG['sslmode']}"
        conn = psycopg.connect(conn_string)
        return conn
    except psycopg.Error as e:
        print(f"Database connection error: {e}")
        return None

def upload_platforms():
    """Upload platform data to the platform table"""
    
    # Platform data with dimensions
    platforms_data = [
        ("Facebook", "1080x1080"),
        ("Facebook", "1080x1920"),
        ("Facebook", "1200x628"),
        ("Instagram", "1080x1080"),
        ("Instagram", "1080x1920"),  # Fixed the asterisk to x
        ("Google", "125x125")        # Fixed the asterisk to x
    ]
    
    try:
        # Connect to database
        conn = get_db_connection()
        if not conn:
            print("Database connection failed")
            return
        
        cursor = conn.cursor()
        
        # Clear existing data (optional - remove if you want to keep existing data)
        cursor.execute("DELETE FROM platform")
        print("Cleared existing platform data")
        
        # Insert platform data
        query = """
        INSERT INTO platform (platform_name, dimension)
        VALUES (%s, %s)
        """
        
        for platform_name, dimension in platforms_data:
            cursor.execute(query, (platform_name, dimension))
            print(f"Inserted: {platform_name} - {dimension}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"Successfully uploaded {len(platforms_data)} platform entries")
        
    except Exception as e:
        print(f"Error uploading platforms: {e}")

if __name__ == '__main__':
    upload_platforms()
