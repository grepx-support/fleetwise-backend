#!/usr/bin/env python3
"""
S3 Log Uploader with Buffering and Resilience
Uploads logs to S3 with 1-2 hour buffering to handle EC2 downtime
"""

import boto3
import os
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
import gzip
import hashlib
from typing import List, Dict, Optional
import threading
from queue import Queue, Empty
import signal
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/log_uploader.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class S3LogUploader:
    def __init__(self, 
                 aws_access_key_id: str = None,
                 aws_secret_access_key: str = None,
                 region_name: str = 'ap-southeast-1',
                 bucket_name: str = None,
                 log_directories: List[str] = None,
                 upload_interval_minutes: int = 120,  # 2 hours default
                 max_buffer_size: int = 1000):
        
        # AWS Configuration
        self.aws_access_key_id = aws_access_key_id or os.getenv('AWS_ACCESS_KEY_ID')
        self.aws_secret_access_key = aws_secret_access_key or os.getenv('AWS_SECRET_ACCESS_KEY')
        self.region_name = region_name
        self.bucket_name = bucket_name or os.getenv('LOG_BUCKET_NAME')
        
        # Configuration
        self.log_directories = log_directories or [
            '/app/logs',  # Backend logs
            '/var/log/nginx',  # Nginx logs
            '/var/log/syslog'  # System logs
        ]
        self.upload_interval = upload_interval_minutes * 60  # Convert to seconds
        self.max_buffer_size = max_buffer_size
        
        # State
        self.running = False
        self.upload_queue = Queue()
        self.upload_thread = None
        self.last_upload_time = datetime.now()
        self.processed_files = set()
        
        # Initialize S3 client
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                region_name=self.region_name
            )
            logger.info(f"Initialized S3 client for bucket: {self.bucket_name}")
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {e}")
            raise
    
    def scan_log_files(self) -> List[Dict]:
        """Scan directories for log files to upload"""
        log_files = []
        
        for directory in self.log_directories:
            if not os.path.exists(directory):
                logger.warning(f"Log directory does not exist: {directory}")
                continue
                
            try:
                for file_path in Path(directory).rglob('*'):
                    if file_path.is_file() and self.should_process_file(file_path):
                        file_stats = file_path.stat()
                        log_files.append({
                            'path': str(file_path),
                            'size': file_stats.st_size,
                            'modified': datetime.fromtimestamp(file_stats.st_mtime),
                            'created': datetime.fromtimestamp(file_stats.st_ctime)
                        })
            except Exception as e:
                logger.error(f"Error scanning directory {directory}: {e}")
        
        # Sort by modification time (oldest first)
        log_files.sort(key=lambda x: x['modified'])
        return log_files
    
    def should_process_file(self, file_path: Path) -> bool:
        """Determine if a file should be processed"""
        # Skip if already processed
        file_hash = self.get_file_hash(file_path)
        if file_hash in self.processed_files:
            return False
        
        # Skip current active log files (ending with .log without timestamp)
        if file_path.name.endswith('.log') and not '_' in file_path.name:
            # Check if it's actively being written to
            try:
                current_size = file_path.stat().st_size
                time.sleep(1)  # Wait a moment
                new_size = file_path.stat().st_size
                if current_size != new_size:
                    logger.debug(f"Skipping active log file: {file_path}")
                    return False
            except Exception:
                pass
        
        # Only process files modified in the last 24 hours
        try:
            modified_time = datetime.fromtimestamp(file_path.stat().st_mtime)
            if datetime.now() - modified_time > timedelta(hours=24):
                return False
        except Exception:
            return False
            
        return True
    
    def get_file_hash(self, file_path: Path) -> str:
        """Generate a hash for file identification"""
        try:
            stat = file_path.stat()
            hash_input = f"{file_path}_{stat.st_size}_{stat.st_mtime}"
            return hashlib.md5(hash_input.encode()).hexdigest()
        except Exception:
            return str(file_path)
    
    def compress_and_upload(self, file_info: Dict) -> bool:
        """Compress file and upload to S3"""
        try:
            file_path = Path(file_info['path'])
            
            # Generate S3 key with timestamp and hostname
            hostname = os.uname().nodename if hasattr(os, 'uname') else 'unknown'
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            original_name = file_path.name
            compressed_name = f"{timestamp}_{hostname}_{original_name}.gz"
            
            # Compress file
            compressed_data = self.compress_file(file_path)
            
            # Upload to S3
            s3_key = f"logs/{datetime.now().strftime('%Y/%m/%d')}/{compressed_name}"
            
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=compressed_data,
                ContentType='application/gzip',
                Metadata={
                    'original_filename': original_name,
                    'hostname': hostname,
                    'upload_timestamp': datetime.now().isoformat(),
                    'original_size': str(file_info['size'])
                }
            )
            
            logger.info(f"Uploaded {original_name} to s3://{self.bucket_name}/{s3_key}")
            
            # Mark as processed
            file_hash = self.get_file_hash(file_path)
            self.processed_files.add(file_hash)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to upload {file_info['path']}: {e}")
            return False
    
    def compress_file(self, file_path: Path) -> bytes:
        """Compress file content"""
        with open(file_path, 'rb') as f:
            content = f.read()
        
        compressed_content = gzip.compress(content)
        compression_ratio = (1 - len(compressed_content) / len(content)) * 100
        logger.debug(f"Compressed {file_path.name}: {len(content)} -> {len(compressed_content)} bytes ({compression_ratio:.1f}% reduction)")
        
        return compressed_content
    
    def batch_upload(self, log_files: List[Dict]) -> int:
        """Upload a batch of log files"""
        successful_uploads = 0
        
        for file_info in log_files[:self.max_buffer_size]:  # Limit batch size
            if self.compress_and_upload(file_info):
                successful_uploads += 1
                # Small delay to avoid overwhelming S3
                time.sleep(0.1)
        
        return successful_uploads
    
    def upload_cycle(self):
        """Single upload cycle"""
        try:
            logger.info("Starting log upload cycle")
            
            # Scan for log files
            log_files = self.scan_log_files()
            
            if not log_files:
                logger.info("No new log files to upload")
                return
            
            logger.info(f"Found {len(log_files)} log files to process")
            
            # Upload files
            successful = self.batch_upload(log_files)
            
            logger.info(f"Upload cycle completed: {successful}/{len(log_files)} files uploaded")
            
            self.last_upload_time = datetime.now()
            
        except Exception as e:
            logger.error(f"Error in upload cycle: {e}")
    
    def start_continuous_upload(self):
        """Start continuous upload service"""
        if self.running:
            logger.warning("Upload service already running")
            return
        
        self.running = True
        self.upload_thread = threading.Thread(target=self._upload_loop, daemon=True)
        self.upload_thread.start()
        logger.info(f"Started continuous log upload service (interval: {self.upload_interval}s)")
    
    def stop_continuous_upload(self):
        """Stop continuous upload service"""
        logger.info("Stopping continuous upload service...")
        self.running = False
        
        if self.upload_thread:
            self.upload_thread.join(timeout=30)
        
        # Final upload before stopping
        self.upload_cycle()
        logger.info("Continuous upload service stopped")
    
    def _upload_loop(self):
        """Main upload loop"""
        while self.running:
            try:
                # Check if it's time to upload
                if (datetime.now() - self.last_upload_time).total_seconds() >= self.upload_interval:
                    self.upload_cycle()
                
                # Sleep for a short time before next check
                time.sleep(60)  # Check every minute
                
            except Exception as e:
                logger.error(f"Error in upload loop: {e}")
                time.sleep(60)
    
    def immediate_upload(self):
        """Trigger immediate upload"""
        logger.info("Triggering immediate upload")
        self.upload_cycle()
    
    def get_status(self) -> Dict:
        """Get current status of the uploader"""
        return {
            'running': self.running,
            'last_upload': self.last_upload_time.isoformat(),
            'processed_files_count': len(self.processed_files),
            'queue_size': self.upload_queue.qsize(),
            'bucket_name': self.bucket_name,
            'upload_interval_seconds': self.upload_interval
        }

# Signal handlers for graceful shutdown
def signal_handler(signum, frame):
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    if 'uploader' in globals():
        uploader.stop_continuous_upload()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Main execution
if __name__ == "__main__":
    # Load configuration from environment or config file
    config = {
        'aws_access_key_id': os.getenv('AWS_ACCESS_KEY_ID'),
        'aws_secret_access_key': os.getenv('AWS_SECRET_ACCESS_KEY'),
        'region_name': os.getenv('AWS_REGION', 'ap-southeast-1'),
        'bucket_name': os.getenv('LOG_BUCKET_NAME'),
        'log_directories': os.getenv('LOG_DIRECTORIES', '/app/logs,/var/log/nginx').split(','),
        'upload_interval_minutes': int(os.getenv('UPLOAD_INTERVAL_MINUTES', '120')),
        'max_buffer_size': int(os.getenv('MAX_BUFFER_SIZE', '1000'))
    }
    
    try:
        uploader = S3LogUploader(**config)
        
        if len(sys.argv) > 1 and sys.argv[1] == '--immediate':
            # Immediate upload mode
            uploader.immediate_upload()
        else:
            # Continuous upload mode
            uploader.start_continuous_upload()
            
            # Keep running
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Received interrupt signal")
                uploader.stop_continuous_upload()
                
    except Exception as e:
        logger.error(f"Failed to start log uploader: {e}")
        sys.exit(1)