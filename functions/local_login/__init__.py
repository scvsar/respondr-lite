import logging
import azure.functions as func
import json
import os
import hashlib
import secrets
import jwt
import datetime
from azure.data.tables import TableClient
from azure.core.exceptions import ResourceNotFoundError

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a login request.')

    try:
        req_body = req.get_json()
    except ValueError:
        return func.HttpResponse(
             "Invalid JSON",
             status_code=400
        )

    email = req_body.get('email')
    password = req_body.get('password')

    if not email or not password:
        return func.HttpResponse(
             "Please pass email and password in the request body",
             status_code=400
        )

    # Configuration
    connection_string = os.environ.get("AzureWebJobsStorage")
    table_name = os.environ.get("LOCAL_USERS_TABLE", "LocalUsers")
    secret_key = os.environ.get("LOCAL_AUTH_SECRET_KEY")
    if not secret_key:
        secret_key = os.environ.get("LOCAL_AUTH_SECRET_FALLBACK")
    if not secret_key:
        secret_key = "dev-local-secret-key"
        logging.warning("LOCAL_AUTH_SECRET_KEY not configured; using dev-local-secret-key fallback")

    if not connection_string:
        logging.error("Missing configuration: AzureWebJobsStorage")
        return func.HttpResponse("Server configuration error", status_code=500)

    try:
        table_client = TableClient.from_connection_string(conn_str=connection_string, table_name=table_name)
        
        # Query for the user by email
        parameters = {"email": email}
        filter_query = "email eq @email"
        
        users = list(table_client.query_entities(query_filter=filter_query, parameters=parameters))
        
        if not users:
            # Fallback: try treating the input 'email' as a username (RowKey)
            try:
                user = table_client.get_entity(partition_key="localuser", row_key=email)
                users = [user]
            except ResourceNotFoundError:
                logging.info(f"User not found: {email}")
                return func.HttpResponse("Invalid credentials", status_code=401)

        user = users[0]
        
        stored_hash = user.get("password_hash")
        stored_salt = user.get("password_salt")
        
        if not stored_hash or not stored_salt:
             logging.warning(f"User {email} has no password hash/salt")
             return func.HttpResponse("Invalid credentials", status_code=401)

        # Verify password
        computed_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            stored_salt.encode('utf-8'),
            100000
        ).hex()
        
        if not secrets.compare_digest(computed_hash, stored_hash):
            logging.info(f"Invalid password for user {email}")
            return func.HttpResponse("Invalid credentials", status_code=401)
            
        # Generate JWT
        payload = {
            'iss': 'local',
            'username': user['RowKey'],
            'email': user.get('email'),
            'display_name': user.get('display_name'),
            'roles': ['user'],
            'is_admin': user.get('is_admin', False),
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }
        
        token = jwt.encode(payload, secret_key, algorithm='HS256')
        
        return func.HttpResponse(
            json.dumps({"token": token}),
            mimetype="application/json",
            status_code=200
        )

    except Exception as e:
        logging.error(f"Login error: {str(e)}")
        return func.HttpResponse("Login failed", status_code=500)
