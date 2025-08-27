"""Local user authentication system for external users (deputies, etc.)."""

import hashlib
import secrets
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from azure.data.tables import TableServiceClient, TableClient
from azure.core.exceptions import ResourceNotFoundError

from .config import (
    LOCAL_USERS_TABLE, LOCAL_AUTH_SECRET_KEY, LOCAL_AUTH_SESSION_HOURS,
    ENABLE_LOCAL_AUTH, APP_TZ, now_tz, is_testing
)

logger = logging.getLogger(__name__)


# In-memory storage for local development when Azure Storage is not available
_local_users_memory_store: Dict[str, Dict[str, Any]] = {}

def get_table_client(table_name: str) -> Optional[TableClient]:
    """Get a table client for the specified table, or None if not available."""
    # Check if we're in local development mode without Azure Storage
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    
    if not connection_string:
        # Fallback to account name and key
        account_name = os.getenv("AZURE_STORAGE_ACCOUNT")
        account_key = os.getenv("AZURE_STORAGE_KEY")
        
        if account_name and account_key:
            connection_string = f"DefaultEndpointsProtocol=https;AccountName={account_name};AccountKey={account_key};EndpointSuffix=core.windows.net"
        else:
            # No Azure Storage configured - use in-memory storage for local development
            logger.info(f"No Azure Storage configured, using in-memory storage for {table_name}")
            return None
    
    try:
        # Create table service client and get table client
        table_service = TableServiceClient.from_connection_string(connection_string)
        table_client = table_service.get_table_client(table_name)
        
        # Ensure table exists
        try:
            table_client.create_table()
            logger.info(f"Created table {table_name}")
        except Exception as e:
            # Table might already exist
            error_msg = str(e).lower()
            if "already exists" in error_msg or "conflict" in error_msg:
                logger.debug(f"Table {table_name} already exists")
            else:
                logger.warning(f"Could not create table {table_name}: {e}")
        
        return table_client
    except Exception as e:
        logger.warning(f"Could not connect to Azure Storage, using in-memory storage: {e}")
        return None


class LocalUser:
    """Represents a local user account."""
    
    def __init__(self, username: str, email: str, display_name: str, 
                 is_admin: bool = False, organization: str = "", 
                 created_at: Optional[datetime] = None):
        self.username = username
        self.email = email
        self.display_name = display_name
        self.is_admin = is_admin
        self.organization = organization
        self.created_at = created_at or now_tz()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "PartitionKey": "localuser",
            "RowKey": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "is_admin": self.is_admin,
            "organization": self.organization,
            "created_at": self.created_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalUser":
        """Create LocalUser from dictionary."""
        created_at = None
        if data.get("created_at"):
            try:
                created_at = datetime.fromisoformat(data["created_at"].replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                created_at = now_tz()
        
        return cls(
            username=data["RowKey"],
            email=data.get("email", ""),
            display_name=data.get("display_name", ""),
            is_admin=data.get("is_admin", False),
            organization=data.get("organization", ""),
            created_at=created_at
        )


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hash a password with salt. Returns (hashed_password, salt)."""
    if salt is None:
        salt = secrets.token_hex(16)
    
    # Use PBKDF2 with SHA-256
    password_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000  # iterations
    )
    return password_hash.hex(), salt


def verify_password(password: str, hashed_password: str, salt: str) -> bool:
    """Verify a password against its hash."""
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, hashed_password)


def create_session_token(user: LocalUser) -> str:
    """Create a JWT session token for a local user."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        raise ValueError("Local authentication is not enabled")
    
    try:
        import jwt
    except ImportError:
        raise ValueError("PyJWT package not installed - required for local authentication")
    
    payload = {
        'username': user.username,
        'email': user.email,
        'display_name': user.display_name,
        'is_admin': user.is_admin,
        'organization': user.organization,
        'auth_type': 'local',
        'exp': datetime.utcnow() + timedelta(hours=LOCAL_AUTH_SESSION_HOURS),
        'iat': datetime.utcnow()
    }
    
    return jwt.encode(payload, LOCAL_AUTH_SECRET_KEY, algorithm='HS256')


def verify_session_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode a JWT session token."""
    try:
        import jwt
    except ImportError:
        logger.error("PyJWT package not installed - required for local authentication")
        return None
    
    try:
        payload = jwt.decode(token, LOCAL_AUTH_SECRET_KEY, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("JWT token has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug(f"Invalid JWT token: {e}")
        return None


async def get_local_user(username: str) -> Optional[LocalUser]:
    """Get a local user by username."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return None
    
    try:
        table_client = get_table_client(LOCAL_USERS_TABLE)
        if table_client is None:
            # Use in-memory storage
            user_data = _local_users_memory_store.get(username)
            if user_data:
                return LocalUser.from_dict(user_data)
            return None
        else:
            # Use Azure Table Storage
            entity = table_client.get_entity("localuser", username)
            return LocalUser.from_dict(entity)
    except ResourceNotFoundError:
        return None
    except Exception as e:
        logger.error(f"Error getting local user {username}: {e}")
        return None


async def verify_local_user(username: str, password: str) -> Optional[LocalUser]:
    """Verify username/password and return user if valid."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return None
    
    try:
        table_client = get_table_client(LOCAL_USERS_TABLE)
        if table_client is None:
            # Use in-memory storage
            entity = _local_users_memory_store.get(username)
            if not entity:
                logger.info(f"Local user {username} not found in memory store")
                return None
        else:
            # Use Azure Table Storage
            entity = table_client.get_entity("localuser", username)
        
        stored_hash = entity.get("password_hash")
        stored_salt = entity.get("password_salt")
        
        if not stored_hash or not stored_salt:
            logger.warning(f"Missing password data for user {username}")
            return None
        
        if verify_password(password, stored_hash, stored_salt):
            return LocalUser.from_dict(entity)
        else:
            logger.info(f"Invalid password for user {username}")
            return None
            
    except ResourceNotFoundError:
        logger.info(f"Local user {username} not found")
        return None
    except Exception as e:
        logger.error(f"Error verifying local user {username}: {e}")
        return None


async def create_local_user(username: str, password: str, email: str, 
                           display_name: str, is_admin: bool = False, 
                           organization: str = "") -> bool:
    """Create a new local user. Returns True if successful."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return False
    
    try:
        # Check if user already exists
        existing = await get_local_user(username)
        if existing:
            logger.warning(f"User {username} already exists")
            return False
        
        # Hash password
        password_hash, salt = hash_password(password)
        
        # Create user entity
        user = LocalUser(username, email, display_name, is_admin, organization)
        entity = user.to_dict()
        entity["password_hash"] = password_hash
        entity["password_salt"] = salt
        
        # Store in table or memory
        table_client = get_table_client(LOCAL_USERS_TABLE)
        if table_client is None:
            # Use in-memory storage
            _local_users_memory_store[username] = entity
            logger.info(f"Created local user in memory: {username} ({email})")
        else:
            # Use Azure Table Storage
            table_client.create_entity(entity)
            logger.info(f"Created local user in Azure Storage: {username} ({email})")
        
        return True
        
    except Exception as e:
        logger.error(f"Error creating local user {username}: {e}")
        return False


async def update_local_user_password(username: str, new_password: str) -> bool:
    """Update a local user's password. Returns True if successful."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return False
    
    try:
        table_client = get_table_client(LOCAL_USERS_TABLE)
        entity = table_client.get_entity("localuser", username)
        
        # Hash new password
        password_hash, salt = hash_password(new_password)
        entity["password_hash"] = password_hash
        entity["password_salt"] = salt
        
        # Update entity
        table_client.update_entity(entity, mode="replace")
        
        logger.info(f"Updated password for local user: {username}")
        return True
        
    except ResourceNotFoundError:
        logger.warning(f"Local user {username} not found for password update")
        return False
    except Exception as e:
        logger.error(f"Error updating password for local user {username}: {e}")
        return False


async def list_local_users() -> list[LocalUser]:
    """List all local users (admin function)."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return []
    
    try:
        table_client = get_table_client(LOCAL_USERS_TABLE)
        entities = table_client.query_entities("PartitionKey eq 'localuser'")
        
        users = []
        for entity in entities:
            try:
                users.append(LocalUser.from_dict(entity))
            except Exception as e:
                logger.warning(f"Error parsing user entity: {e}")
                continue
        
        return users
        
    except Exception as e:
        logger.error(f"Error listing local users: {e}")
        return []


def extract_session_token_from_request(request) -> Optional[str]:
    """Extract session token from request (header or cookie)."""
    # Try Authorization header first
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]  # Remove "Bearer " prefix
    
    # Try session cookie
    session_cookie = request.cookies.get("session_token")
    if session_cookie:
        return session_cookie
    
    return None