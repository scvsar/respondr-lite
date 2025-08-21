# Storage Configuration Guide

Respondr now supports multiple storage backends with automatic fallback capabilities.

## Environment Variables

### Primary Storage Backend
Set `STORAGE_BACKEND` to choose your primary storage:
- `redis` (default) - Use Redis for storage
- `azure_table` - Use Azure Table Storage
- `file` - Use JSON files on disk
- `memory` - Use in-memory storage (not persistent)

### Fallback Storage Backend
Set `STORAGE_FALLBACK` to choose fallback when primary fails:
- `memory` (default) - Use in-memory storage as fallback
- `file` - Use JSON files as fallback
- `redis` - Use Redis as fallback (if primary is not redis)

### Redis Configuration
- `REDIS_HOST` - Redis server hostname (default: localhost)
- `REDIS_PORT` - Redis server port (default: 6379)
- `REDIS_DB` - Redis database number (default: 0)

### Azure Table Storage Configuration
- `AZURE_STORAGE_CONNECTION_STRING` - Azure Storage connection string
- `AZURE_TABLE_NAME` - Table name (default: responderMessages)

### File Storage Configuration
- `STORAGE_MESSAGES_FILE` - Active messages file (default: messages.json)
- `STORAGE_DELETED_FILE` - Deleted messages file (default: deleted_messages.json)

## Example Configurations

### Redis Primary, Memory Fallback (Default)
```bash
STORAGE_BACKEND=redis
STORAGE_FALLBACK=memory
REDIS_HOST=localhost
REDIS_PORT=6379
```

### Azure Table Primary, File Fallback
```bash
STORAGE_BACKEND=azure_table
STORAGE_FALLBACK=file
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...
AZURE_TABLE_NAME=responderMessages
STORAGE_MESSAGES_FILE=./data/messages.json
STORAGE_DELETED_FILE=./data/deleted_messages.json
```

### File Primary, Memory Fallback
```bash
STORAGE_BACKEND=file
STORAGE_FALLBACK=memory
STORAGE_MESSAGES_FILE=./data/messages.json
STORAGE_DELETED_FILE=./data/deleted_messages.json
```

### Development/Testing
```bash
STORAGE_BACKEND=memory
STORAGE_FALLBACK=file
```

## Automatic Fallback Behavior

1. **Primary Available**: System uses primary storage backend
2. **Primary Fails**: System automatically switches to fallback backend
3. **Both Fail**: System creates emergency in-memory storage
4. **Recovery**: When primary becomes available again, system switches back

## Health Monitoring

The storage system continuously monitors backend health and switches automatically.
You can check current storage status via the `/api/storage-info` endpoint (if implemented).

## Testing Mode

When `is_testing=True` in config, the system automatically uses in-memory storage
to avoid conflicts with production data.

## Migration Notes

This new storage system is backwards compatible with existing Redis-based storage.
All existing functions continue to work unchanged.