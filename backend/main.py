from fastapi import FastAPI, UploadFile, File, HTTPException, Security, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from sshtunnel import SSHTunnelForwarder
from datetime import datetime, timezone
from dotenv import load_dotenv
from mediameta import ImageMetadata, VideoMetadata
import traceback
import psycopg2
import boto3
import logging
from botocore.config import Config
import os
import io
import uuid
import hmac
import hashlib
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from configuration import *

# Load credentials
# load_dotenv("../.env.dev")
load_dotenv()
API_KEY = os.getenv("API_KEY") # Backend access API key authentication
SECRET_SIGNING_KEY = os.getenv("SECRET_SIGNING_KEY") # Secret key for signing URLs
DB_SCHEMA = os.getenv("DB_SCHEMA")
DB_TABLE = os.getenv("DB_TABLE")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# Initialize logging
logger = logging.getLogger("uvicorn")

# Initialize FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    logger.info("Shutting down gracefully...")
    cursor.close()
    conn.close()
    tunnel.stop()
    logger.info("All connections closed.")
app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # allow_origins=[os.getenv("FRONTEND_ENTRY"), os.getenv("FRONTEND_URL")],
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize SSH tunnel
tunnel = SSHTunnelForwarder(
    os.getenv("SSH_HOST"),
    ssh_username=os.getenv("SSH_USER"),
    ssh_password=os.getenv("SSH_PASSWORD"),
    remote_bind_addresses=[
        (os.getenv("DB_HOST"), int(os.getenv("DB_PORT"))),  # Bind to Postgres
        (os.getenv("GARAGE_HOST"), int(os.getenv("GARAGE_PORT"))),  # Bind to Garage
    ]
)
tunnel.start()

# Initialize PostgreSQL connection
conn = psycopg2.connect(
    host=os.getenv("DB_HOST"),
    port=tunnel.local_bind_ports[0],
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
)
cursor = conn.cursor()

# Initialize Garage S3 client
s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("GARAGE_KEY"),
    aws_secret_access_key=os.getenv("SECRET_GARAGE_KEY"),
    endpoint_url=f"http://{os.getenv('GARAGE_HOST')}:{tunnel.local_bind_ports[1]}",
    region_name="garage",
    config=Config(
        signature_version='s3v4',
        s3={'addressing_style': 'path'}
    )
)

def verify_api_key(header_api_key: str = Header(None, alias="header_key"), query_api_key: str = Query(None, alias="query_key")):
    if header_api_key == API_KEY or query_api_key == API_KEY:
        return
    raise HTTPException(status_code=401)

def generate_signed_url(filename: str, expiry_minutes: int = 15) -> str:
    """Generate temporary signed URL for secure streaming"""
    expiry = datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)
    expiry_timestamp = int(expiry.timestamp())
    
    message = f"{filename}:{expiry_timestamp}"
    signature = hmac.new(
        SECRET_SIGNING_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return f"/stream/{filename}?expires={expiry_timestamp}&signature={signature}"

def verify_signed_url(filename: str, expires: int, signature: str) -> bool:
    """Verify signed URL is valid and not expired"""
    # Check expiry
    if datetime.now(timezone.utc).timestamp() > expires:
        return False
    
    # Verify signature
    message = f"{filename}:{expires}"
    expected_signature = hmac.new(
        SECRET_SIGNING_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected_signature)

# Write an object and metadata
@app.post("/object/")
def write_object(file: UploadFile = File(...), request: Request = None, _ = Security(verify_api_key)):
    # Extract content and metadata from request and file
    device = request.headers.get("User-Agent")
    ext = file.filename.split('.')[-1].lower()
    if ext not in MEDIA_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: .{ext}")
    data = file.file.read()
    size = len(data)
    if size == 0:
        raise HTTPException(status_code=400, detail="File is empty")
    key = f"{uuid.uuid4()}.{ext}"
    created_date = datetime.now(timezone.utc)
    is_img = ext in IMAGE_EXTS
    try:
        file_obj = io.BytesIO(data)
        if ext in IMAGE_EXTS:
            try:
                img = ImageMetadata(file_obj)
                if img.creation_date:
                    created_date = datetime.fromisoformat(img.creation_date).replace(tzinfo=timezone.utc)
            except Exception:
                pass
        elif ext in VIDEO_EXTS:
            try:
                video = VideoMetadata(file_obj)
                if video.creation_date:
                    created_date = datetime.fromisoformat(video.creation_date).replace(tzinfo=timezone.utc)
            except Exception:
                pass
    except Exception:
        pass
    # Writing to both PostgreSQL and Garage
    try:
        # Metadata into PostgreSQL
        cursor.execute(
            f"""
            INSERT INTO {DB_SCHEMA}.{DB_TABLE} 
                (key, original_filename, file_type, size, device, 
                uploaded_date, created_date, tag, is_img)
            VALUES 
                (%s, %s, %s, %s, %s, 
                %s, %s, %s, %s)
            """,
            [key, file.filename, ext, size, device, 
             datetime.now(timezone.utc), created_date, None, is_img]
        )
        conn.commit()
        # File to Garage
        s3_client.upload_fileobj(
            Fileobj=io.BytesIO(data),
            Bucket=BUCKET_NAME,
            Key=key,
        )
        return {"message": f"{file.filename} written successfully", "key": key}
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# Read an object
@app.get("/object/{filename}")
def read_object(filename: str, range: str = Header(None), _ = Security(verify_api_key)):
    ext = filename.split('.')[-1].lower()
    if ext not in MEDIA_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: .{ext}")
    
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=filename)
        data = response["Body"].read()
        file_size = len(data)
        
        # For videos, support range requests for streaming
        if ext in VIDEO_EXTS and range:
            # Parse range header (e.g., "bytes=0-1023")
            range_match = range.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else file_size - 1
            end = min(end, file_size - 1)
            
            chunk = data[start:end + 1]
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(chunk)),
            }
            return Response(content=chunk, status_code=206, media_type=MEDIA_TYPES[ext], headers=headers)
        
        # For images or non-range requests, return full content
        return Response(content=data, media_type=MEDIA_TYPES[ext], headers={"Accept-Ranges": "bytes"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# Read an object metadata
@app.get("/object/{filename}/metadata")
def read_metadata(filename: str, _ = Security(verify_api_key)):
    try:
        cursor.execute(
            f"""
            SELECT 
                key, original_filename, file_type, size, device, 
                uploaded_date, created_date, tag, is_img
            FROM {DB_SCHEMA}.{DB_TABLE} WHERE key = %s
            """,
            [filename]
        )
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Metadata not found")
        return {
            "key": row[0],
            "original_filename": row[1],
            "file_type": row[2],
            "size": row[3],
            "device": row[4],
            "uploaded_date": row[5].isoformat(),
            "created_date": row[6].isoformat(),
            "tag": row[7],
            "is_img": row[8],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Delete an object and its metadata
@app.delete("/object/{filename}")
def delete_object(filename: str, _ = Security(verify_api_key)):
    try:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=filename)
        cursor.execute(
            f"DELETE FROM {DB_SCHEMA}.{DB_TABLE} WHERE key = %s",
            [filename]
        )
        conn.commit()
        return {"message": f"{filename} deleted successfully"}
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# List all keys of objects
@app.get("/objects/")
def list_objects(_ = Security(verify_api_key)):
    try:
        cursor.execute(
            f"SELECT key, size, uploaded_date FROM {DB_SCHEMA}.{DB_TABLE} ORDER BY uploaded_date DESC"
        )
        rows = cursor.fetchall()
        files = [
            {
                "filename": row[0],
                "size": row[1],
                "last_modified": row[2].isoformat(),
            }
            for row in rows
        ]
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Read keys of filtered objects
@app.get("/objects/filter")
def list_filtered_objects(created_date_start: str = None, created_date_end: str = None, tag: str = None, is_img: bool = None, _ = Security(verify_api_key)):
    """
    Filter objects by created_date range, tag, or is_img status
    """
    try:
        query = f"SELECT key FROM {DB_SCHEMA}.{DB_TABLE} WHERE 1=1"
        params = []
        
        if created_date_start:
            query += " AND created_date >= %s"
            params.append(created_date_start)
        
        if created_date_end:
            query += " AND created_date <= %s"
            params.append(created_date_end)
        
        if tag:
            query += " AND tag = %s"
            params.append(tag)
        
        if is_img is not None:
            query += " AND is_img = %s"
            params.append(is_img)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        files = [row[0] for row in rows]
        
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Update tag for an object
@app.patch("/object/{filename}/tag")
def update_tag(filename: str, tag_data: dict, _ = Security(verify_api_key)):
    try:
        tag = tag_data.get("tag", "").strip() or None
        cursor.execute(
            f"UPDATE {DB_SCHEMA}.{DB_TABLE} SET tag = %s WHERE key = %s",
            [tag, filename]
        )
        conn.commit()
        return {"message": f"Tag updated for {filename}", "tag": tag}
    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# Read video with streaming
@app.get("/stream/{filename}")
def stream_object(
    filename: str, 
    expires: int = Query(...), 
    signature: str = Query(...), 
    range: str = Header(None)
):
    ext = filename.split('.')[-1].lower()
    if ext not in MEDIA_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type")
    
    if not verify_signed_url(filename, expires, signature):
        raise HTTPException(status_code=403, detail="Invalid or expired URL")
    
    try:
        # Get object metadata first
        head_response = s3_client.head_object(Bucket=BUCKET_NAME, Key=filename)
        file_size = head_response['ContentLength']
        
        if range:
            range_match = range.replace("bytes=", "").split("-")
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else file_size - 1
            end = min(end, file_size - 1)
            
            # Download only the requested range
            response = s3_client.get_object(
                Bucket=BUCKET_NAME, 
                Key=filename,
                Range=f'bytes={start}-{end}'
            )
            chunk = response['Body'].read()
            
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(chunk)),
                "Content-Type": MEDIA_TYPES[ext],
            }
            return Response(content=chunk, status_code=206, headers=headers)
        
        # Full file request
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=filename)
        data = response['Body'].read()
        
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Type": MEDIA_TYPES[ext],
            "Content-Length": str(file_size),
        }
        return Response(content=data, headers=headers)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# Add endpoint to generate signed URL
@app.get("/object/{filename}/stream-url")
def get_stream_url(filename: str, _ = Security(verify_api_key)):
    """Generate temporary signed URL for streaming"""
    ext = filename.split('.')[-1].lower()
    if ext not in MEDIA_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type")
    
    signed_url = generate_signed_url(filename)
    return {"url": signed_url}

# Health check
@app.get("/")
def health_check():
    return {"status": "ok", "message": "Backend is running"}

# Database health check
@app.get("/db-health")
def db_health_check():
    try:
        conn.rollback() # Reset connection state
        cursor.execute("SELECT 1")
        return {"status": "ok", "message": "Database is running"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/garage-health")
def garage_health_check():
    try:
        s3_client.head_bucket(Bucket=BUCKET_NAME)
        return {"status": "ok", "message": "Garage is running"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))