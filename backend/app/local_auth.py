"""Local user authentication system for external users (deputies, etc.)."""

import asyncio
import hashlib
import secrets
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from azure.data.tables import TableClient
from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError

from .config import (
    LOCAL_USERS_TABLE, LOCAL_AUTH_SECRET_KEY, LOCAL_AUTH_SESSION_HOURS,
    ENABLE_LOCAL_AUTH, APP_TZ, now_tz, is_testing
)

logger = logging.getLogger(__name__)


# In-memory storage for local development when Azure Storage is not available
_local_users_memory_store: Dict[str, Dict[str, Any]] = {}

class LocalAuthStorageError(RuntimeError):
    """Local-user storage cannot complete an operation."""


def get_table_client(table_name: str) -> Optional[TableClient]:
    backend = os.getenv("LOCAL_AUTH_STORAGE_BACKEND", "azure_table").lower()
    if is_testing or backend == "memory":
        return None
    if backend != "azure_table":
        raise LocalAuthStorageError("Invalid local-user storage configuration")
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        account_name = os.getenv("AZURE_STORAGE_ACCOUNT")
        account_key = os.getenv("AZURE_STORAGE_KEY")
        if account_name and account_key:
            connection_string = f"DefaultEndpointsProtocol=https;AccountName={account_name};AccountKey={account_key};EndpointSuffix=core.windows.net"
    if not connection_string:
        raise LocalAuthStorageError("Local-user storage is not configured")
    try:
        client = TableClient.from_connection_string(
            connection_string, table_name=table_name, connection_timeout=5, read_timeout=15, retry_total=2,
        )
        try:
            client.create_table()
        except ResourceExistsError:
            pass
        return client
    except Exception as exc:
        raise LocalAuthStorageError("Local-user storage is unavailable") from exc


class LocalUser:
    """Represents a local user account."""
    
    def __init__(self, username: str, email: str, display_name: str, 
                 is_admin: bool = False, organization: str = "", 
                 created_at: Optional[datetime] = None):
        self.username = username
        self.email = email
        self.display_name = display_name
        self.is_admin = is_admin is True
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
        'iss': 'local',
        'exp': datetime.now(timezone.utc) + timedelta(hours=LOCAL_AUTH_SESSION_HOURS),
        'iat': datetime.now(timezone.utc)
    }
    
    if not LOCAL_AUTH_SECRET_KEY:
        raise ValueError("Local authentication signing secret is not configured")
    return jwt.encode(payload, LOCAL_AUTH_SECRET_KEY, algorithm='HS256')


def verify_session_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode a JWT session token."""
    from .auth.dependencies import require_auth
    import jwt

    try:
        if jwt.get_unverified_header(token).get("alg") != "HS256":
            return None
        return require_auth(None, token)
    except Exception:
        logger.debug("Local session token validation failed")
        return None


async def get_local_user(username: str) -> Optional[LocalUser]:
    """Get a local user by username."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return None
    
    try:
        table_client = await asyncio.to_thread(get_table_client, LOCAL_USERS_TABLE)
        if table_client is None:
            # Use in-memory storage
            user_data = _local_users_memory_store.get(username)
            if user_data:
                return LocalUser.from_dict(user_data)
            return None
        else:
            # Use Azure Table Storage
            entity = await asyncio.to_thread(table_client.get_entity, "localuser", username)
            return LocalUser.from_dict(entity)
    except ResourceNotFoundError:
        return None
    except Exception as exc:
        logger.error("Local-user storage operation failed")
        raise LocalAuthStorageError("Local-user storage is unavailable") from exc


async def get_local_user_by_email(email: str) -> Optional[LocalUser]:
    """Get a local user by email address."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return None
    
    try:
        table_client = await asyncio.to_thread(get_table_client, LOCAL_USERS_TABLE)
        if table_client is None:
            # Use in-memory storage
            for user_data in _local_users_memory_store.values():
                if user_data.get("email", "").lower() == email.lower():
                    return LocalUser.from_dict(user_data)
            return None
        else:
            # Use Azure Table Storage - Query by email
            # Note: This is a scan, but acceptable for small number of local users
            filter_query = "PartitionKey eq 'localuser' and email eq @email"
            entities = await asyncio.to_thread(lambda: list(table_client.query_entities(filter_query, parameters={"email": email})))
            
            for entity in entities:
                return LocalUser.from_dict(entity)
            # Older records can contain mixed-case email addresses.
            entities = await asyncio.to_thread(lambda: list(table_client.query_entities("PartitionKey eq 'localuser'")))
            for entity in entities:
                if str(entity.get("email", "")).casefold() == email.casefold():
                    return LocalUser.from_dict(entity)
            return None
            
    except Exception as exc:
        logger.error("Local-user storage operation failed")
        raise LocalAuthStorageError("Local-user storage is unavailable") from exc


async def verify_local_user(username_or_email: str, password: str) -> Optional[LocalUser]:
    """Verify username/password and return user if valid."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return None
    
    try:
        user = await get_local_user(username_or_email)
        
        # If not found by username, try email if it looks like one
        if not user and "@" in username_or_email:
            user = await get_local_user_by_email(username_or_email)
            
        if not user:
            logger.info(f"Local user {username_or_email} not found")
            return None

        # Get the password hash/salt (need to fetch raw entity again or store it in LocalUser?)
        # LocalUser object doesn't store hash/salt. We need to fetch the entity.
        # But we already fetched it in get_local_user... but that returns LocalUser object.
        # We need to refactor slightly or fetch again.
        
        # Let's fetch the entity using the resolved username
        username = user.username
        
        table_client = await asyncio.to_thread(get_table_client, LOCAL_USERS_TABLE)
        if table_client is None:
            entity = _local_users_memory_store.get(username)
        else:
            entity = await asyncio.to_thread(table_client.get_entity, "localuser", username)
        
        stored_hash = entity.get("password_hash")
        stored_salt = entity.get("password_salt")
        
        if not stored_hash or not stored_salt:
            logger.warning(f"Missing password data for user {username}")
            return None
        
        if await asyncio.to_thread(verify_password, password, stored_hash, stored_salt):
            return LocalUser.from_dict(entity)
        else:
            logger.info(f"Invalid password for user {username}")
            return None
            
    except ResourceNotFoundError:
        logger.info(f"Local user {username_or_email} not found")
        return None
    except Exception as exc:
        logger.error("Local-user storage operation failed")
        raise LocalAuthStorageError("Local-user storage is unavailable") from exc


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
        password_hash, salt = await asyncio.to_thread(hash_password, password)
        
        # Create user entity
        user = LocalUser(username, email, display_name, is_admin, organization)
        entity = user.to_dict()
        entity["password_hash"] = password_hash
        entity["password_salt"] = salt
        
        # Store in table or memory
        table_client = await asyncio.to_thread(get_table_client, LOCAL_USERS_TABLE)
        if table_client is None:
            # Use in-memory storage
            if username in _local_users_memory_store:
                return False
            _local_users_memory_store[username] = entity
            logger.info(f"Created local user in memory: {username} ({email})")
        else:
            # Use Azure Table Storage
            await asyncio.to_thread(table_client.create_entity, entity)
            logger.info(f"Created local user in Azure Storage: {username} ({email})")
        
        return True
        
    except ResourceExistsError:
        return False
    except Exception as exc:
        logger.error("Local-user storage operation failed")
        raise LocalAuthStorageError("Local-user storage is unavailable") from exc


async def update_local_user_password(username: str, new_password: str) -> bool:
    """Update a local user's password. Returns True if successful."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return False
    
    try:
        table_client = await asyncio.to_thread(get_table_client, LOCAL_USERS_TABLE)
        if table_client is None:
            if username not in _local_users_memory_store:
                return False
            password_hash, salt = await asyncio.to_thread(hash_password, new_password)
            if username not in _local_users_memory_store:
                return False
            _local_users_memory_store[username].update(password_hash=password_hash, password_salt=salt)
            return True
        entity = await asyncio.to_thread(table_client.get_entity, "localuser", username)

        # Hash new password
        password_hash, salt = await asyncio.to_thread(hash_password, new_password)
        entity["password_hash"] = password_hash
        entity["password_salt"] = salt
        
        # Update entity
        password_fields = {key: entity[key] for key in ("PartitionKey", "RowKey", "password_hash", "password_salt")}
        await asyncio.to_thread(table_client.update_entity, password_fields, mode="merge")
        
        logger.info(f"Updated password for local user: {username}")
        return True
        
    except ResourceNotFoundError:
        logger.warning(f"Local user {username} not found for password update")
        return False
    except Exception as exc:
        logger.error("Local-user storage operation failed")
        raise LocalAuthStorageError("Local-user storage is unavailable") from exc


async def list_local_users() -> list[LocalUser]:
    """List all local users (admin function)."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return []
    
    try:
        table_client = await asyncio.to_thread(get_table_client, LOCAL_USERS_TABLE)
        if table_client is None:
            return [LocalUser.from_dict(row) for row in _local_users_memory_store.values()]
        entities = await asyncio.to_thread(lambda: list(table_client.query_entities("PartitionKey eq 'localuser'")))
        
        users = []
        for entity in entities:
            try:
                users.append(LocalUser.from_dict(entity))
            except Exception as e:
                logger.warning(f"Error parsing user entity: {e}")
                continue
        
        return users
        
    except Exception as exc:
        logger.error("Local-user storage operation failed")
        raise LocalAuthStorageError("Local-user storage is unavailable") from exc


async def delete_local_user(username: str) -> bool:
    """Delete a local user (admin function)."""
    if not ENABLE_LOCAL_AUTH and not is_testing:
        return False
    
    try:
        table_client = await asyncio.to_thread(get_table_client, LOCAL_USERS_TABLE)
        
        if table_client is None:
            # Use in-memory storage
            if username in _local_users_memory_store:
                del _local_users_memory_store[username]
                logger.info(f"Deleted local user from memory: {username}")
                return True
            return False
        
        # Delete from Azure Table Storage
        row_key = username
        partition_key = "localuser"
        
        await asyncio.to_thread(table_client.delete_entity, partition_key=partition_key, row_key=row_key)
        logger.info(f"Deleted local user: {username}")
        return True
        
    except ResourceNotFoundError:
        logger.warning(f"User {username} not found for deletion")
        return False
    except Exception as exc:
        logger.error("Local-user storage operation failed")
        raise LocalAuthStorageError("Local-user storage is unavailable") from exc


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
