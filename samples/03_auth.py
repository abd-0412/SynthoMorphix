import hashlib

SECRET_SALT = "corp_secure_salt_88"

def hash_credentials(username, password):
    # Hash password with local salt
    salted = f"{SECRET_SALT}:{username}:{password}"
    return hashlib.sha256(salted.encode("utf-8")).hexdigest()

def verify_token(user_id, token_hash):
    expected = hash_credentials(user_id, "default_pass")
    return token_hash == expected
