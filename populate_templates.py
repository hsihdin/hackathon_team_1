import psycopg
import os
import json
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
        conn_string = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}?sslmode={DB_CONFIG['sslmode']}"
        conn = psycopg.connect(conn_string)
        return conn
    except psycopg.Error as e:
        print(f"Database connection error: {e}")
        return None

def populate_templates():
    """Populate platform table with template data"""
    
    # Template data for each platform
    templates_data = {
        "facebook": {
            "1080x1080": {
                "version1": {
                    "top": 266,
                    "url": "https://hackathon-shyftlabs-team1.s3.us-east-2.amazonaws.com/ad_templates/facebook/1080_1080/fb_1080_1080_1.png",
                    "left": 19,
                    "right": 419,
                    "bottom": 815
                },
                "version2": {
                    "top": 77,
                    "url": "https://hackathon-shyftlabs-team1.s3.us-east-2.amazonaws.com/ad_templates/facebook/1080_1080/fb_1080_1080_2.png",
                    "left": 36,
                    "right": 413,
                    "bottom": 526
                }
            },
            "1080x1920": {
                "version1": {
                    "top": 400,
                    "url": "https://hackathon-shyftlabs-team1.s3.us-east-2.amazonaws.com/ad_templates/facebook/1080_1920/fb_1080_1920_1.png",
                    "left": 50,
                    "right": 450,
                    "bottom": 1200
                }
            },
            "1200x628": {
                "version1": {
                    "top": 150,
                    "url": "https://hackathon-shyftlabs-team1.s3.us-east-2.amazonaws.com/ad_templates/facebook/1200_628/fb_1200_628_1.png",
                    "left": 231,
                    "right": 849,
                    "bottom": 588
                }
            }
        },
        "instagram": {
            "1080x1080": {
                "version1": {
                    "top": 200,
                    "url": "https://hackathon-shyftlabs-team1.s3.us-east-2.amazonaws.com/ad_templates/instagram/1080_1080/ig_1080_1080_1.png",
                    "left": 100,
                    "right": 500,
                    "bottom": 700
                }
            },
            "1080x1920": {
                "version1": {
                    "top": 300,
                    "url": "https://hackathon-shyftlabs-team1.s3.us-east-2.amazonaws.com/ad_templates/instagram/1080_1920/ig_1080_1920_1.png",
                    "left": 80,
                    "right": 480,
                    "bottom": 1000
                }
            }
        }
    }
    
    try:
        # Connect to database
        conn = get_db_connection()
        if not conn:
            print("Database connection failed")
            return
        
        cursor = conn.cursor()
        
        # Update each platform with template data
        for platform_name, templates in templates_data.items():
            print(f"Updating templates for {platform_name}...")
            
            # Convert templates to JSON
            templates_json = json.dumps(templates)
            
            # Update platform table
            query = """
            UPDATE platform 
            SET templates = %s
            WHERE platform_name ILIKE %s
            """
            
            cursor.execute(query, (templates_json, platform_name))
            
            if cursor.rowcount > 0:
                print(f"  Updated {platform_name} with {len(templates)} dimensions")
            else:
                print(f"  No platform found with name: {platform_name}")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("Template population completed successfully")
        
    except Exception as e:
        print(f"Error populating templates: {e}")

if __name__ == '__main__':
    populate_templates()
