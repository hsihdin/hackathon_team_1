from flask import Flask, request, jsonify
import psycopg
from psycopg.rows import dict_row
import os
import json
import requests
from PIL import Image
import io
import base64
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# cors
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
    return response

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


def crop_image(image_url, selected_platforms):
    """
    Crop the image to the desired dimensions for each platform
    Returns a JSON with all cropped images
    """
    try:
        print(f"Starting crop process for URL: {image_url}")
        print(f"Selected platforms: {selected_platforms}")
        
        # Download the image from URL
        response = requests.get(image_url)
        response.raise_for_status()
        print(f"Image downloaded successfully, size: {len(response.content)} bytes")
        
        # Open the image
        original_image = Image.open(io.BytesIO(response.content))
        print(f"Original image size: {original_image.size}")
        
        # Platform dimensions mapping
        platform_dimensions = {
            "Facebook": ["1080x1080", "1080x1920", "1200x628"],
            "Instagram": ["1080x1080", "1080x1920"],
            "Google": ["125x125"],
            "facebook": ["1080x1080", "1080x1920", "1200x628"],
            "instagram": ["1080x1080", "1080x1920"],
            "google": ["125x125"],
            "snapchat": ["1080x1920", "1080x1080"]
        }
        
        cropped_images = {}
        
        print(f"Processing platforms: {selected_platforms}")
        for platform in selected_platforms:
            print(f"Processing platform: {platform}")
            if platform in platform_dimensions:
                platform_crops = {}
                
                for dimension in platform_dimensions[platform]:
                    print(f"    Processing dimension: {dimension}")
                    width, height = map(int, dimension.split('x'))
                    
                    # Calculate aspect ratios
                    original_ratio = original_image.width / original_image.height
                    target_ratio = width / height
                    
                    # Crop strategy: center crop to maintain aspect ratio
                    if original_ratio > target_ratio:
                        # Original is wider, crop width
                        new_width = int(original_image.height * target_ratio)
                        left = (original_image.width - new_width) // 2
                        cropped = original_image.crop((left, 0, left + new_width, original_image.height))
                    else:
                        # Original is taller, crop height
                        new_height = int(original_image.width / target_ratio)
                        top = (original_image.height - new_height) // 2
                        cropped = original_image.crop((0, top, original_image.width, top + new_height))
                    # Resize to target dimensions
                    resized = cropped.resize((width, height), Image.Resampling.LANCZOS)
                    
                    # Convert to base64
                    buffer = io.BytesIO()
                    resized.save(buffer, format='JPEG', quality=85)
                    img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    
                    platform_crops[dimension] = f"data:image/jpeg;base64,{img_base64}"
                
                cropped_images[platform] = platform_crops
        
        return cropped_images
        
    except Exception as e:
        print(f"Error cropping image: {e}")
        return {}


@app.route('/creative/add-new-creative', methods=['POST'])
def add_new_creative():
    """
    Add a new creative to the database
    Expected input: {
        "title": "creative title",
        "description": "creative description", 
        "campaign": "campaign name",
        "formatType": "format type",
        "tags": ["tag1", "tag2"],
        "dynamicElements": {
            "productName": false,
            "price": false,
            "callToAction": false,
            "background": false
        },
        "image": "s3_url_string",
        "selectedPlatforms": ["platform1", "platform2"],
        "add_item_id": "uuid"
    }
    Returns: {"message": "Creative added successfully", "creative_id": id, "s3_url": "s3_url"}
    """
    try:
        data = request.get_json()
        if not data or 'title' not in data or 'description' not in data or 'add_item_id' not in data:
            return jsonify({'error': 'Missing required fields: title, description, add_item_id'}), 400
        
        # Extract data from request
        title = data['title']
        description = data['description']
        campaign = data.get('campaign', '')
        format_type = data.get('formatType', '')
        tags = data.get('tags', [])
        dynamic_elements = data.get('dynamicElements', {})
        image = data.get('image', '')  # This should be a URL string
        selected_platforms = data.get('selectedPlatforms', [])
        add_item_id = data['add_item_id']
        
        # Convert complex objects to JSON strings for storage
        tags_json = json.dumps(tags)
        dynamic_elements_json = json.dumps(dynamic_elements)
        selected_platforms_json = json.dumps(selected_platforms)
        
        # check image url
        if not image.startswith('https://'):
            return jsonify({'error': 'Invalid image URL'}), 400
        
        # Crop the image
        crop = crop_image(image, selected_platforms)
        if crop is None:
            crop = {}  # Set empty dict if cropping fails
        image_json = json.dumps(crop)  # Store cropped images in image_data
        # Connect to databaseƒ
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor()
        
        # Insert new creative into database
        query = """
        INSERT INTO creative_new (
            creative_title, creative_description, campaign, format_type, 
            tags, dynamic_elements, image_data, creative_s3_url, 
            selected_platforms, ad_item_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING creative_id
        """
        
        cursor.execute(query, (
            title, description, campaign, format_type, 
            tags_json, dynamic_elements_json, image_json, image,
            selected_platforms_json, add_item_id
        ))
        new_creative_id = cursor.fetchone()[0]
        
        conn.commit()
        cursor.close()
        conn.close()
        
        # Print all cropped images for debugging
        print("=" * 50)
        print("CROPPED IMAGES SUMMARY:")
        print("=" * 50)
        if crop:
            for platform, dimensions in crop.items():
                print(f"\n{platform.upper()}:")
                for dimension, base64_data in dimensions.items():
                    print(f"  {dimension}: {base64_data[:50]}... (truncated)")
                    print(f"    Full length: {len(base64_data)} characters")
        else:
            print("No cropped images generated")
        print("=" * 50)
        
        return jsonify({'message': 'Creative added successfully', 'creative_id': new_creative_id}), 201
        
    except Exception as e:
        print(f"Error adding creative: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/creative/<int:creative_id>', methods=['GET'])
def get_creative_by_id(creative_id):
    """
    Get creative data by creative_id
    Returns: All creative data including cropped images
    """
    try:
        # Connect to database
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor(row_factory=dict_row)
        
        # Query to get creative by ID
        query = """
        SELECT 
            creative_id,
            ad_item_id,
            creative_title,
            creative_description,
            creative_s3_url,
            campaign,
            format_type,
            tags,
            dynamic_elements,
            image_data,
            selected_platforms,
            created_at
        FROM creative_new 
        WHERE creative_id = %s
        """
        
        cursor.execute(query, (creative_id,))
        result = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if not result:
            return jsonify({'error': 'Creative not found'}), 404
        
        # Convert the result to a dictionary and handle JSON fields
        creative_data = dict(result)
        
        # Parse JSON fields if they exist and are strings
        if creative_data.get('tags') and isinstance(creative_data['tags'], str):
            creative_data['tags'] = json.loads(creative_data['tags'])
        if creative_data.get('dynamic_elements') and isinstance(creative_data['dynamic_elements'], str):
            creative_data['dynamic_elements'] = json.loads(creative_data['dynamic_elements'])
        if creative_data.get('image_data') and isinstance(creative_data['image_data'], str):
            creative_data['image_data'] = json.loads(creative_data['image_data'])
        if creative_data.get('selected_platforms') and isinstance(creative_data['selected_platforms'], str):
            creative_data['selected_platforms'] = json.loads(creative_data['selected_platforms'])
        
        return jsonify(creative_data), 200
        
    except Exception as e:
        print(f"Error getting creative: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/creatives', methods=['GET'])
def get_all_creatives():
    """
    Get all creatives from the database
    Optional query parameters:
    - limit: number of creatives to return (default: 50)
    - offset: number of creatives to skip (default: 0)
    - platform: filter by platform (e.g., 'facebook', 'instagram')
    - search_query: search in title, description, and campaign (case-insensitive)
    Returns: List of all creatives
    """
    try:
        # Get query parameters
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        platform_filter = request.args.get('platform', None)
        search_query = request.args.get('search_query', None)
        
        # Validate parameters
        if limit > 100:
            limit = 100  # Max limit to prevent performance issues
        if limit < 1:
            limit = 1
        
        # Connect to database
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor(row_factory=dict_row)
        
        # Build query based on filters
        base_query = """
        SELECT 
            creative_id,
            ad_item_id,
            creative_title,
            creative_description,
            creative_s3_url,
            campaign,
            format_type,
            tags,
            dynamic_elements,
            image_data,
            selected_platforms,
            created_at
        FROM creative_new 
        """
        
        where_conditions = []
        query_params = []
        
        # Add platform filter
        if platform_filter:
            where_conditions.append("selected_platforms::text ILIKE %s")
            query_params.append(f'%{platform_filter}%')
        
        # Add search query filter
        if search_query:
            where_conditions.append("""
                (creative_title ILIKE %s OR 
                 creative_description ILIKE %s OR 
                 campaign ILIKE %s)
            """)
            search_pattern = f'%{search_query}%'
            query_params.extend([search_pattern, search_pattern, search_pattern])
        
        # Build final query
        if where_conditions:
            query = base_query + " WHERE " + " AND ".join(where_conditions)
        else:
            query = base_query
        
        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        query_params.extend([limit, offset])
        
        cursor.execute(query, query_params)
        
        results = cursor.fetchall()
        
        # Get total count for pagination
        count_query = "SELECT COUNT(*) as total FROM creative_new"
        count_params = []
        
        if platform_filter or search_query:
            count_conditions = []
            
            if platform_filter:
                count_conditions.append("selected_platforms::text ILIKE %s")
                count_params.append(f'%{platform_filter}%')
            
            if search_query:
                count_conditions.append("""
                    (creative_title ILIKE %s OR 
                     creative_description ILIKE %s OR 
                     campaign ILIKE %s)
                """)
                search_pattern = f'%{search_query}%'
                count_params.extend([search_pattern, search_pattern, search_pattern])
            
            count_query += " WHERE " + " AND ".join(count_conditions)
        
        cursor.execute(count_query, count_params)
        
        total_count = cursor.fetchone()['total']
        
        cursor.close()
        conn.close()
        
        # Process results
        creatives = []
        for result in results:
            creative_data = dict(result)
            
            # Parse JSON fields if they exist and are strings
            if creative_data.get('tags') and isinstance(creative_data['tags'], str):
                creative_data['tags'] = json.loads(creative_data['tags'])
            if creative_data.get('dynamic_elements') and isinstance(creative_data['dynamic_elements'], str):
                creative_data['dynamic_elements'] = json.loads(creative_data['dynamic_elements'])
            if creative_data.get('image_data') and isinstance(creative_data['image_data'], str):
                creative_data['image_data'] = json.loads(creative_data['image_data'])
            if creative_data.get('selected_platforms') and isinstance(creative_data['selected_platforms'], str):
                creative_data['selected_platforms'] = json.loads(creative_data['selected_platforms'])
            
            creatives.append(creative_data)
        
        # Prepare response
        response = {
            'creatives': creatives,
            'pagination': {
                'total': total_count,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + limit) < total_count
            }
        }
        
        # Add filter information to response
        filters = {}
        if platform_filter:
            filters['platform'] = platform_filter
        if search_query:
            filters['search_query'] = search_query
        
        if filters:
            response['filters'] = filters
        
        return jsonify(response), 200
        
    except Exception as e:
        print(f"Error getting all creatives: {e}")
        return jsonify({'error': 'Internal server error'}), 500




@app.route('/crop-image', methods=['POST'])
def crop_image_endpoint():
    """
    Crop image to different platform dimensions
    Expected input: {
        "image_url": "https://example.com/image.jpg",
        "selected_platforms": ["Facebook", "Instagram"]
    }
    Returns: {"cropped_images": {"Facebook": {"1080x1080": "base64_data", ...}, ...}}
    """
    try:
        data = request.get_json()
        if not data or 'image_url' not in data or 'selected_platforms' not in data:
            return jsonify({'error': 'Missing required fields: image_url, selected_platforms'}), 400
        
        image_url = data['image_url']
        selected_platforms = data['selected_platforms']
        
        # Crop the image
        cropped_images = crop_image(image_url, selected_platforms)
        
        return jsonify({'cropped_images': cropped_images}), 200
        
    except Exception as e:
        print(f"Error in crop endpoint: {e}")
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
                CREATE TABLE IF NOT EXISTS creative_new (
                    creative_id SERIAL PRIMARY KEY,
                    ad_item_id VARCHAR(255) NOT NULL,
                    creative_title VARCHAR(255) NOT NULL,
                    creative_description TEXT,
                    creative_s3_url VARCHAR(500),
                    campaign VARCHAR(255),
                    format_type VARCHAR(100),
                    tags JSONB,
                    dynamic_elements JSONB,
                    image_data JSONB,
                    selected_platforms JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
