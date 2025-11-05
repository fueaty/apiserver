import sys
import os
sys.path.insert(0, '/root/apiserver')

from app.api.v1.endpoints.auth import load_valid_auth_keys
from app.core.config import config_manager

print("Testing auth key loading...")
auth_keys = load_valid_auth_keys()
print(f"Number of valid auth keys: {len(auth_keys)}")

if auth_keys:
    print("First auth key:", list(auth_keys)[0])

print("\nTesting JWT secret loading...")
try:
    creds = config_manager.get_credentials()
    jwt_secret = creds.get("jwt", {}).get("secret_key")
    print(f"JWT secret: {jwt_secret}")
except Exception as e:
    print(f"Error loading JWT secret: {e}")
