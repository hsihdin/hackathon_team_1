from flask import Flask, request, jsonify
import psycopg
from psycopg.rows import dict_row
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

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

@app.route('/creative', methods=['POST'])
def get_creative():
    """
    Get creative data based on adTag
    Expected input: {"adTag": "my ad tag"}
    Returns: {"creative": {"id": 1, "versions": [{"id": "", "url": ""}, ...]}}
    """
    try:
        # Parse request
        data = request.get_json()
        if not data or 'adTag' not in data:
            return jsonify({'error': 'Missing adTag in request'}), 400
        
        ad_tag = data['adTag']
        
        # Connect to database
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor(row_factory=dict_row)
        
        # Query to get creatives based on adTag (matching against creative_title for demo)
        # In a real scenario, you might have an ad_tags table or similar
        query = """
        SELECT creative_id, creative_title, creative_description, creative_s3_url, ad_item_id
        FROM creative 
        WHERE creative_title ILIKE %s 
        ORDER BY creative_id
        LIMIT 10
        """
        
        cursor.execute(query, (f'%{ad_tag}%',))
        results = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        if not results:
            return jsonify({'error': 'No creatives found for the given adTag'}), 404
        
        # Format response - group all matching creatives as versions
        # Taking the first creative_id as the main creative id
        main_creative_id = results[0]['creative_id']
        
        versions = []
        for row in results:
            versions.append({
                "id": str(row['creative_id']),
                "url": row['creative_s3_url'] or ""
            })
        
        response = {
            "creative": {
                "id": main_creative_id,
                "versions": versions
            }
        }
        
        return jsonify(response), 200
        
    except Exception as e:
        print(f"Error processing request: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Create tables if they don't exist (optional - for development)
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            
            # Create platform table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS platform (
                    platform_id SERIAL PRIMARY KEY,
                    platform_name VARCHAR(255) NOT NULL,
                    dimension VARCHAR(100)
                )
            """)
            
            # Create creative table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS creative (
                    creative_id SERIAL PRIMARY KEY,
                    ad_item_id INTEGER NOT NULL,
                    creative_title VARCHAR(255) NOT NULL,
                    creative_description TEXT,
                    creative_s3_url VARCHAR(500)
                )
            """)
            
            conn.commit()
            cursor.close()
            conn.close()
            print("Database tables created successfully")
    except Exception as e:
        print(f"Error creating tables: {e}")
    
    # Use PORT environment variable for production
    port = int(os.environ.get('PORT', 5001))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
