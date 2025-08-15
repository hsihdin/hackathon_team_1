from flask import Flask, request, jsonify
import psycopg
from psycopg.rows import dict_row
import os
from dotenv import load_dotenv
import json
import requests
from PIL import Image
import io
import base64
import time
import boto3
from botocore.exceptions import ClientError

# Import the working Google GenAI pattern
from google import genai
from google.genai import types
import PIL.Image

import logging
logging.basicConfig(level=logging.DEBUG)
import boto3
import uuid

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

# Initialize Google GenAI client
GENAI_ENABLED = False
try:
    # Test client creation
    test_client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
    GENAI_ENABLED = True
    print("Google GenAI client initialized successfully")
except Exception as e:
    print(f"Google GenAI client initialization failed: {e}")
    GENAI_ENABLED = False

def create_simple_overlay(product_image, template_image):
    """Create a simple overlay of product on template as fallback"""
    print("going for overlayyyyy")
    try:
        # Resize product image to fit on template
        template_width, template_height = template_image.size
        
        # Make product image smaller (25% of template width)
        product_width = template_width // 4
        product_ratio = product_image.size[1] / product_image.size[0]
        product_height = int(product_width * product_ratio)
        
        # Resize product image
        product_resized = product_image.resize((product_width, product_height), Image.Resampling.LANCZOS)
        
        # Create a copy of template
        result_image = template_image.copy()
        
        # Calculate position (center of template)
        x = (template_width - product_width) // 2
        y = (template_height - product_height) // 2
        
        # Paste product onto template (handle transparency if needed)
        if product_resized.mode == 'RGBA':
            result_image.paste(product_resized, (x, y), product_resized)
        else:
            result_image.paste(product_resized, (x, y))
        
        return result_image
    except Exception as e:
        print(f"Error creating overlay: {e}")
        return None

def optimize_image_for_api(image, max_size=(1024, 1024), quality=85):
    """Optimize image for API calls - resize and compress"""
    try:
        # Convert to RGB if necessary
        if image.mode in ('RGBA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = background
        
        # Resize if too large
        if image.size[0] > max_size[0] or image.size[1] > max_size[1]:
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            print(f"Resized image to {image.size}")
        
        return image
    except Exception as e:
        print(f"Error optimizing image: {e}")
        return image

# Configure AWS S3 (Optional)
try:
    s3_client = boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_REGION', 'us-east-1')
    )
    S3_BUCKET = os.getenv('S3_BUCKET', 'hackathon-ads')
    S3_ENABLED = True
except Exception as e:
    print(f"S3 not configured: {e}")
    s3_client = None
    S3_BUCKET = None
    S3_ENABLED = False

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'dbname': os.getenv('DB_NAME', 'hackathon'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'password'),
    'port': os.getenv('DB_PORT', '5432'),
    'sslmode': os.getenv('DB_SSLMODE', 'prefer')
}

# S3 configuration
S3_CONFIG = {
    'bucket_name': os.getenv('S3_BUCKET_NAME', 'your-bucket-name'),
    'region': os.getenv('AWS_REGION', 'us-east-1')
}

def upload_image_to_s3(image_data, filename):
    """Upload image data to S3 and return the URL"""
    try:
        # Check if AWS credentials are available
        aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
        aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        bucket_name = S3_CONFIG['bucket_name']
        
        print(f"Checking S3 configuration:")
        print(f"  AWS_ACCESS_KEY_ID: {'Set' if aws_access_key else 'Not set'}")
        print(f"  AWS_SECRET_ACCESS_KEY: {'Set' if aws_secret_key else 'Not set'}")
        print(f"  S3_BUCKET_NAME: {bucket_name}")
        print(f"  AWS_REGION: {S3_CONFIG['region']}")
        
        if not aws_access_key or not aws_secret_key:
            print("ERROR: AWS credentials not found in environment variables")
            print("Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY")
            return None
        
        if bucket_name == 'your-bucket-name':
            print("ERROR: S3_BUCKET_NAME not set")
            print("Please set S3_BUCKET_NAME environment variable")
            return None
        
        print(f"Attempting to upload to S3 bucket: {bucket_name}")
        
        s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=S3_CONFIG['region']
        )
        
        # Test S3 connection
        try:
            s3_client.head_bucket(Bucket=bucket_name)
            print(f"Successfully connected to S3 bucket: {bucket_name}")
        except Exception as bucket_error:
            print(f"ERROR: Cannot access S3 bucket '{bucket_name}': {bucket_error}")
            return None
        
        # Upload to S3
        print(f"Uploading file: {filename}")
        s3_client.put_object(
            Bucket=bucket_name,
            Key=f"cropped-images/{filename}",
            Body=image_data,
            ContentType='image/jpeg'
            # Removed ACL='public-read' as bucket doesn't support ACLs
        )
        
        s3_url = f"https://{bucket_name}.s3.{S3_CONFIG['region']}.amazonaws.com/cropped-images/{filename}"
        print(f"Successfully uploaded to S3: {s3_url}")
        return s3_url
        
    except Exception as e:
        print(f"ERROR uploading to S3: {e}")
        print(f"Error type: {type(e).__name__}")
        return None



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

def download_image_from_local(file_path):
    """Load image from local file path and return PIL Image"""
    try:
        if os.path.exists(file_path):
            return Image.open(file_path)
        else:
            print(f"Local file not found: {file_path}")
            return None
    except Exception as e:
        print(f"Error loading local image {file_path}: {e}")
        return None

def save_image_locally(image, filename):
    """Save PIL Image to local directory and return file path"""
    try:
        # Create local directory if it doesn't exist
        local_dir = os.getenv('LOCAL_IMAGE_DIR', './generated_images')
        os.makedirs(local_dir, exist_ok=True)
        
        file_path = os.path.join(local_dir, filename)
        image.save(file_path, 'PNG')
        return file_path
    except Exception as e:
        print(f"Error saving image locally: {e}")
        return None

def download_image_from_s3(bucket, s3_key):
    """Download image from S3 and return PIL Image"""
    if not S3_ENABLED:
        print("S3 not enabled, skipping S3 download")
        return None
    try:
        print(f"Downloading from S3: bucket={bucket}, key={s3_key}")
        response = s3_client.get_object(Bucket=bucket, Key=s3_key)
        image_data = response['Body'].read()
        print(f"Successfully downloaded {len(image_data)} bytes from S3")
        return Image.open(io.BytesIO(image_data))
    except ClientError as e:
        print(f"Error downloading image from S3 {bucket}/{s3_key}: {e}")
        return None
    except Exception as e:
        print(f"Error processing S3 image {bucket}/{s3_key}: {e}")
        return None

def upload_image_to_s3(image, s3_key):
    """Upload PIL Image to S3 and return URL"""
    if not S3_ENABLED:
        print("S3 not enabled, skipping S3 upload")
        return None
    try:
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=buffer,
            ContentType='image/png'
        )
        
        return f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return None

def download_image_from_url(url):
    """Download image from URL, local path, or S3 and return PIL Image"""
    try:
        print(f"Processing URL: {url}")
        
        # Check if it's a local file path
        if url.startswith('./') or url.startswith('/') or (len(url) > 1 and url[1] == ':'):
            return download_image_from_local(url)
        
        # Check if it's an s3:// URL
        elif url.startswith('s3://'):
            s3_parts = url.replace('s3://', '').split('/', 1)
            if len(s3_parts) == 2:
                bucket, key = s3_parts
                return download_image_from_s3(bucket, key)
        
        # Check if it's an S3 HTTPS URL
        elif 's3.amazonaws.com' in url:
            if '.s3.amazonaws.com/' in url:
                bucket = url.split('//')[1].split('.s3.amazonaws.com')[0]
                key = url.split('.s3.amazonaws.com/')[1]
            else:
                parts = url.split('s3.amazonaws.com/')[1].split('/', 1)
                bucket = parts[0]
                key = parts[1] if len(parts) > 1 else ''
            return download_image_from_s3(bucket, key)
        
        # Regular URL download
        else:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return Image.open(io.BytesIO(response.content))
            
    except Exception as e:
        print(f"Error downloading: {e}")
        return None

@app.route('/generate-ad-gemini', methods=['POST'])
def generate_ad_gemini():
    """Generate ad using the exact working Gemini pattern"""
    start_time = time.time()
    
    try:
        if not GENAI_ENABLED:
            return jsonify({'error': 'Google GenAI client not available'}), 500
        
        data = request.get_json()
        product_url = data.get('product_image_url')
        template_url = data.get('template_image_url')
        custom_prompt = (""""You are an image editing model. Do not modify any part of the image except the specified rectangular area. Do not change any other element apart from adding an image
 Keep all text, gradients, prices, reviews, and background elements exactly as they are.
 The input creative contains a placeholder rectangle located at:
 Top-left pixel: [79, 53]
 Bottom-right pixel: [672, 444]
 Paste the user-provided product photo into that rectangle, resizing it proportionally to exactly fit.
 Preserve sharpness and edges. Do not rotate, crop, or alter the product. Do not add extra shadows, reflections, or text.
 Output the final composite image in the same resolution as the input creative.
 Ensure zero changes to any pixels outside the placeholder rectangle."

""")
        
        if not product_url or not template_url:
            return jsonify({'error': 'Both product_image_url and template_image_url required'}), 400
        
        print(f"Downloading product: {product_url}")
        product_image = download_image_from_url(product_url)
        if not product_image:
            return jsonify({'error': 'Failed to download product image'}), 400
        
        print(f"Downloading template: {template_url}")
        template_image = download_image_from_url(template_url)
        if not template_image:
            return jsonify({'error': 'Failed to download template image'}), 400
        
        # Use the exact working prompt pattern
        if custom_prompt:
            text_input = custom_prompt
        else:
            text_input = """You are an expert graphic designer AI.
Task:
Embed the product image into the designated placeholder area on the uploaded advertising template.
Constraints:
1. Maintain the original layout, text, colors, and design elements of the template exactly as they are. Do NOT move, resize, or alter any other elements.
2. The product image must fit perfectly into the placeholder slot, aligned naturally with the design.
3. Preserve the perspective, shadows, and aesthetics of the original template.
4. Output the final image in PNG format with the same resolution as the original template.
5. Do not add extra text or branding. Only replace the placeholder with the product image.
Input: Use the uploaded template as the base and the product image.
Output: A single PNG image with the product embedded exactly into the placeholder slot.
Use the product that I am uploading, to be embedded in the template."""
        
        try:
            print("Calling Gemini with working pattern...")
            
            # Use the exact working pattern
            client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
            
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview-image-generation",
                contents=[text_input, template_image, product_image],
                config=types.GenerateContentConfig(
                    response_modalities=['TEXT', 'IMAGE']
                )
            )
            
            print("Received response from Gemini")
            
            # Process response using the exact working pattern
            generated_image = None
            response_text = ""
            
            for part in response.candidates[0].content.parts:
                if part.text is not None:
                    response_text += part.text
                    print(f"Gemini response text: {part.text}")
                elif part.inline_data is not None:
                    generated_image = Image.open(io.BytesIO(part.inline_data.data))
                    print(f"Generated image received: {generated_image.size}")
                    break
            
            if generated_image:
                # Save the generated image
                filename = f"gemini_generated_{int(time.time())}.png"
                local_path = save_image_locally(generated_image, filename)
                
                # Convert to base64
                buffer = io.BytesIO()
                generated_image.save(buffer, format='PNG')
                image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                
                # Try S3 upload
                s3_url = None
                if S3_ENABLED:
                    try:
                        s3_key = f"generated/{filename}"
                        s3_url = upload_image_to_s3(generated_image, s3_key)
                        print(f"Saved to S3: {s3_url}")
                    except Exception as e:
                        print(f"S3 upload failed: {e}")
                
                processing_time = time.time() - start_time
                
                return jsonify({
                    'status': 'success',
                    'method': 'gemini_2.0_flash_image_generation',
                    'generated_image_path': local_path,
                    'generated_image_base64': image_base64,
                    's3_url': s3_url,
                    'processing_time': f"{processing_time:.2f}s",
                    'gemini_response_text': response_text,
                    'generated_image_size': list(generated_image.size),
                    'input_images': {
                        'product_url': product_url,
                        'template_url': template_url,
                        'product_size': list(product_image.size),
                        'template_size': list(template_image.size)
                    }
                }), 200
            
            else:
                # No image generated, fall back to overlay
                print("No image generated by Gemini, creating overlay fallback")
                fallback_image = create_simple_overlay(product_image, template_image)
                
                if fallback_image:
                    filename = f"fallback_overlay_{int(time.time())}.png"
                    local_path = save_image_locally(fallback_image, filename)
                    
                    buffer = io.BytesIO()
                    fallback_image.save(buffer, format='PNG')
                    image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    
                    processing_time = time.time() - start_time
                    
                    return jsonify({
                        'status': 'success',
                        'method': 'fallback_overlay',
                        'generated_image_path': local_path,
                        'generated_image_base64': image_base64,
                        'processing_time': f"{processing_time:.2f}s",
                        'gemini_response_text': response_text,
                        'note': 'Gemini did not generate image, used fallback overlay'
                    }), 200
                else:
                    return jsonify({
                        'error': 'No image generated and fallback failed',
                        'gemini_response': response_text,
                        'processing_time': f"{(time.time() - start_time):.2f}s"
                    }), 500
                
        except Exception as e:
            print(f"Gemini generation error: {e}")
            return jsonify({
                'error': 'Gemini image generation failed',
                'details': str(e),
                'processing_time': f"{(time.time() - start_time):.2f}s"
            }), 500
        
    except Exception as e:
        processing_time = time.time() - start_time
        return jsonify({
            'error': str(e),
            'processing_time': f"{processing_time:.2f}s"
        }), 500

@app.route('/test-working-pattern', methods=['POST'])
def test_working_pattern():
    """Test the exact working pattern from your example"""
    try:
        if not GENAI_ENABLED:
            return jsonify({'error': 'Google GenAI client not available'}), 400
        
        data = request.get_json()
        test_prompt = data.get('prompt', 'Create a professional product advertisement')
        
        print("Testing exact working pattern...")
        
        # Use exact pattern
        client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
        
        response = client.models.generate_content(
            model="gemini-2.0-flash-preview-image-generation",
            contents=[test_prompt],
            config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE']
            )
        )
        
        generated_image = None
        response_text = ""
        
        for part in response.candidates[0].content.parts:
            if part.text is not None:
                response_text += part.text
            elif part.inline_data is not None:
                generated_image = Image.open(io.BytesIO(part.inline_data.data))
                
                # Convert to base64
                buffer = io.BytesIO()
                generated_image.save(buffer, format='PNG')
                image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                
                return jsonify({
                    'status': 'success',
                    'generated_image_base64': image_base64,
                    'generated_image_size': list(generated_image.size),
                    'response_text': response_text
                }), 200
        
        return jsonify({
            'status': 'text_only',
            'response_text': response_text
        }), 200
        
    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'genai_enabled': GENAI_ENABLED,
        's3_enabled': S3_ENABLED,
        'gemini_key_exists': bool(os.getenv('GEMINI_API_KEY'))
    }), 200

# Keep all your existing endpoints
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
        print(ad_tag)
        
        # Query to get creatives based on adTag (matching against creative_title for demo)
        # In a real scenario, you might have an ad_tags table or similar
        query = f"""
        SELECT creative_id, creative_title, creative_description, creative_s3_url, ad_item_id
        FROM creative_new
        WHERE tags::text LIKE %s
        LIMIT 10
        """
        print(query)
        
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
                "imageUrl": row['creative_s3_url'] or ""
            })
        
        response = {
            "creative": {
                "linkUrl": "https://google.com",
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
        print(f"Starting crop process for S3 URL: {image_url}")
        print(f"Selected platforms: {selected_platforms}")
        
        # Download the image from S3 URL
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        print(f"Image downloaded successfully from S3, size: {len(response.content)} bytes")
        
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
                    
                    # Convert to base64 first
                    buffer = io.BytesIO()
                    resized.save(buffer, format='JPEG', quality=85)
                    image_bytes = buffer.getvalue()
                    img_base64 = base64.b64encode(image_bytes).decode('utf-8')
                    
                    # Create image object with base64 data
                    image_object = {
                        "base64": f"data:image/jpeg;base64,{img_base64}",
                        "width": width,
                        "height": height,
                        "format": "JPEG",
                        "quality": 85
                    }
                    
                    # Generate unique filename
                    filename = f"{uuid.uuid4()}_{platform}_{dimension}.jpg"
                    
                    # Upload base64 image object to S3
                    s3_url = upload_image_to_s3(image_bytes, filename)
                    if s3_url:
                        # Add S3 URL to the image object
                        image_object["s3_url"] = s3_url
                        platform_crops[dimension] = image_object
                        print(f"    Uploaded {dimension} to S3: {s3_url}")
                    else:
                        print(f"    Failed to upload {dimension} to S3, keeping base64 only")
                        platform_crops[dimension] = image_object
                
                cropped_images[platform] = platform_crops
        
        return cropped_images
        
    except requests.exceptions.RequestException as e:
        print(f"Error downloading image from S3: {e}")
        return {}
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
        "image": "https://s3.amazonaws.com/bucket/image.jpg",
        "imageUrl": "https://s3.amazonaws.com/bucket/image.jpg",  // Alternative field name
        "selectedPlatforms": ["platform1", "platform2"],
        "add_item_id": "uuid"
    }
    Returns: {"message": "Creative added successfully", "creative_id": id, "s3_url": "s3_url"}
    """
    try:
        data = request.get_json()
        print(f"Received request data: {data}")
        
        if not data:
            return jsonify({'error': 'No JSON data received'}), 400
        
        if 'title' not in data or 'description' not in data or 'add_item_id' not in data:
            missing_fields = []
            if 'title' not in data:
                missing_fields.append('title')
            if 'description' not in data:
                missing_fields.append('description')
            if 'add_item_id' not in data:
                missing_fields.append('add_item_id')
            return jsonify({'error': f'Missing required fields: {", ".join(missing_fields)}'}), 400
        
        # Extract data from request
        title = data['title']
        description = data['description']
        campaign = data.get('campaign', '')
        format_type = data.get('formatType', '')
        tags = data.get('tags', [])
        dynamic_elements = data.get('dynamicElements', {})
        
        # Handle both 'image' and 'imageUrl' fields
        image = data.get('imageUrl') or data.get('image', '')
        if isinstance(image, dict) and not image:
            image = data.get('imageUrl', '')  # Use imageUrl if image is empty dict
        
        selected_platforms = data.get('selectedPlatforms', [])
        add_item_id = data['add_item_id']
        
        # Convert complex objects to JSON strings for storage
        tags_json = json.dumps(tags)
        dynamic_elements_json = json.dumps(dynamic_elements)
        selected_platforms_json = json.dumps(selected_platforms)
        
        # Validate S3 image URL
        if not image or not isinstance(image, str):
            print(f"Error: Invalid image field - {type(image)}: {image}")
            return jsonify({'error': 'Invalid S3 image URL - must be a non-empty string'}), 400
        
        # Basic S3 URL validation (should start with https:// and contain s3)
        if not (image.startswith('https://') and ('s3' in image.lower() or 'amazonaws.com' in image.lower())):
            print(f"Warning: Image URL may not be a valid S3 URL: {image}")
            # Don't return error, just log warning and continue
        
        # Crop the image from S3
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
        print("CROPPED IMAGES WITH BASE64 AND S3 URL:")
        print("=" * 50)
        if crop:
            for platform, dimensions in crop.items():
                print(f"\n{platform.upper()}:")
                for dimension, image_obj in dimensions.items():
                    if isinstance(image_obj, dict):
                        print(f"  {dimension}:")
                        print(f"    Width: {image_obj.get('width')}px")
                        print(f"    Height: {image_obj.get('height')}px")
                        print(f"    Format: {image_obj.get('format')}")
                        print(f"    Base64: {image_obj.get('base64')[:50]}... (truncated)")
                        if image_obj.get('s3_url'):
                            print(f"    S3 URL: {image_obj.get('s3_url')}")
                        else:
                            print(f"    S3 URL: Failed to upload")
                    else:
                        print(f"  {dimension}: {image_obj}")
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
        "image_url": "https://s3.amazonaws.com/bucket/image.jpg",
        "selected_platforms": ["Facebook", "Instagram"]
    }
    Returns: {"cropped_images": {"Facebook": {"1080x1080": {"base64": "...", "s3_url": "...", "width": 1080, "height": 1080}, ...}, ...}}
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


@app.route('/s3-test', methods=['GET'])
def test_s3_config():
    """Test S3 configuration"""
    try:
        aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
        aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        bucket_name = S3_CONFIG['bucket_name']
        region = S3_CONFIG['region']
        
        config_status = {
            'aws_access_key_id': 'Set' if aws_access_key else 'Not set',
            'aws_secret_access_key': 'Set' if aws_secret_key else 'Not set',
            's3_bucket_name': bucket_name,
            'aws_region': region,
            'status': 'Configured' if (aws_access_key and aws_secret_key and bucket_name != 'your-bucket-name') else 'Not configured'
        }
        
        # Test S3 connection if credentials are available
        if aws_access_key and aws_secret_key and bucket_name != 'your-bucket-name':
            try:
                s3_client = boto3.client(
                    's3',
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_key,
                    region_name=region
                )
                s3_client.head_bucket(Bucket=bucket_name)
                config_status['s3_connection'] = 'Success'
                config_status['bucket_access'] = 'Accessible'
            except Exception as e:
                config_status['s3_connection'] = 'Failed'
                config_status['bucket_access'] = str(e)
        else:
            config_status['s3_connection'] = 'Not tested'
            config_status['bucket_access'] = 'Not tested'
        
        return jsonify(config_status), 200
        
    except Exception as e:
        return jsonify({'error': f'S3 test failed: {e}'}), 500

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

 
