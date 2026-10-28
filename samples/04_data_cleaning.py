import re

def sanitize_record(record):
    clean_name = record["name"].strip().title()
    clean_email = record["email"].strip().lower()
    raw_phone = record.get("phone", "")
    normalized_phone = re.sub(r"[^\d]", "", raw_phone)
    return {
        "name": clean_name,
        "email": clean_email,
        "phone": normalized_phone,
    }

def clean_dataset(records):
    return [sanitize_record(r) for r in records if r.get("email")]
