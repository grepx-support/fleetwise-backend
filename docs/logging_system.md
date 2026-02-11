# Comprehensive Logging System Documentation

## Overview

This logging system provides comprehensive monitoring for both frontend and backend applications with S3 integration for persistent storage and analysis.

## Components

### 1. Backend Logging Enhancements

#### System Monitor (`backend/utils/system_monitor.py`)
- Collects CPU, memory, disk, network, and process metrics
- Runs continuously with configurable intervals
- Logs structured JSON data for easy parsing

#### Request Logger (`backend/utils/request_logger.py`)
- Tracks request/response performance metrics
- Monitors memory and CPU usage per request
- Provides detailed timing information

#### Frontend Logs API (`backend/api/frontend_logs.py`)
- Receives frontend log batches
- Processes and stores frontend telemetry
- Supports both individual and batch log submissions

### 2. Frontend Logging Service

#### Frontend Logger (`frontend/services/frontendLogger.ts`)
- Buffers logs for offline scenarios
- Automatically flushes logs periodically
- Captures user interactions, errors, and performance metrics
- Integrates with React error boundaries

#### React Hooks (`frontend/hooks/useFrontendLogging.ts`)
- `useFrontendLogging` - Component-level logging
- `useApiLogging` - API call monitoring
- `useErrorBoundaryLogging` - Error boundary integration

### 3. S3 Log Uploader

#### Log Uploader Script (`scripts/s3_log_uploader.py`)
- Scans log directories for new files
- Compresses logs before upload
- Buffers uploads for 1-2 hour intervals
- Handles EC2 downtime gracefully
- Automatic retry mechanisms

## Setup Instructions

### Backend Setup

1. **Install dependencies:**
```bash
pip install psutil boto3
```

2. **Configure environment variables:**
```bash
# In your .env file
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
LOG_BUCKET_NAME=your_bucket_name
AWS_REGION=ap-southeast-1
```

3. **The system automatically integrates with existing Flask app**

### Frontend Setup

1. **Install axios dependency:**
```bash
npm install axios
```

2. **Use the logging hooks in your components:**
```typescript
import { useFrontendLogging } from '@/hooks/useFrontendLogging';

const MyComponent = () => {
  const { logUserAction, logError } = useFrontendLogging('MyComponent');
  
  const handleClick = () => {
    logUserAction('button_click', 'submit_button');
  };
  
  // Component logic...
};
```

### S3 Uploader Setup

1. **Create S3 bucket:**
```bash
aws s3 mb s3://fleetwise-logs-production --region ap-southeast-1
```

2. **Deploy systemd service:**
```bash
sudo cp deploy/log-uploader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable log-uploader
sudo systemctl start log-uploader
```

3. **Configure environment:**
```bash
# Create /app/config/log_uploader.env
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
LOG_BUCKET_NAME=fleetwise-logs-production
UPLOAD_INTERVAL_MINUTES=120
```

## Log Structure

### Backend System Metrics
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "hostname": "ip-172-31-1-100",
  "cpu": {
    "cpu_percent": 25.5,
    "cpu_count": 2,
    "cpu_frequency_mhz": 2500.0
  },
  "memory": {
    "memory_total_mb": 8192,
    "memory_used_mb": 2048,
    "memory_percent": 25.0
  }
}
```

### Request Logs
```json
{
  "timestamp": "2024-01-15T10:30:01Z",
  "request_id": "1705315801123456",
  "method": "POST",
  "url": "https://api.example.com/users",
  "duration_ms": 150.5,
  "status_code": 200,
  "memory_delta_mb": 2.5,
  "cpu_user_time": 0.1234
}
```

### Frontend Logs
```json
{
  "timestamp": "2024-01-15T10:30:02Z",
  "level": "INFO",
  "message": "USER_ACTION",
  "data": {
    "action": "button_click",
    "element": "submit_button",
    "sessionId": "sess_abc123",
    "userId": "user123"
  }
}
```

## Monitoring and Alerts

### Log Analysis Commands

```bash
# View system metrics
tail -f /app/logs/app.log | grep SYSTEM_METRICS

# Monitor slow requests
tail -f /app/logs/app.log | grep SLOW_REQUEST

# Check frontend errors
tail -f /app/logs/app.log | grep FRONTEND_ERROR

# Monitor S3 uploader status
systemctl status log-uploader
journalctl -u log-uploader -f
```

### CloudWatch Integration (Optional)

Create CloudWatch alarms for:
- High CPU usage (>80%)
- Memory pressure (>85%)
- Disk space (<10% free)
- Application errors (>10/min)

## Troubleshooting

### Common Issues

1. **S3 Upload Failures:**
   - Check AWS credentials
   - Verify bucket permissions
   - Ensure network connectivity

2. **High Log Volume:**
   - Adjust log levels in production
   - Increase upload interval
   - Implement log rotation policies

3. **Frontend Logging Not Working:**
   - Verify API endpoint availability
   - Check CORS configuration
   - Review browser console for errors

### Performance Tuning

- Adjust `UPLOAD_INTERVAL_MINUTES` based on log volume
- Modify `MAX_BUFFER_SIZE` for memory considerations
- Tune system monitoring frequency for production loads

## Security Considerations

- Never log sensitive user data
- Use IAM roles instead of hardcoded credentials in production
- Implement log retention policies
- Enable S3 bucket encryption
- Regular security audits of log content

## Maintenance

Regular maintenance tasks:
- Monitor disk space usage
- Review log retention policies
- Update AWS SDK versions
- Audit log access permissions
- Backup critical log data