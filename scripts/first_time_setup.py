import sys
import os
import sqlite3
import hashlib
from datetime import datetime, timezone

def setup_admin():
    print("=====================================================")
    print("           LEADSWEEP FIRST-TIME SETUP               ")
    print("=====================================================")
    print("First-time setup detected. Please configure your Admin account.")
    print("This account will have UNLIMITED credits & full platform access.\n")

    email = input("Enter Admin Email (e.g. user@example.com): ").strip()
    while not email or "@" not in email:
        email = input("Please enter a valid email address: ").strip()

    import getpass
    pwd = getpass.getpass("Enter Admin Password: ").strip()
    while not pwd:
        pwd = getpass.getpass("Password cannot be empty. Enter Admin Password: ").strip()

    name = input("Enter Admin Name [Admin]: ").strip() or "Admin"

    print("\n--- Optional API Credentials (press Enter to skip/use defaults) ---")
    groq_api = input("Enter GROQ_API_KEY (optional): ").strip()
    gemini_api = input("Enter GEMINI_API_KEY (optional): ").strip()
    twitter_auth = input("Enter X / Twitter auth_token cookie (optional): ").strip()
    twitter_ct0 = input("Enter X / Twitter ct0 cookie (optional): ").strip()

    # 1. Update/Create .env file
    env_lines = []
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            env_lines = f.readlines()
    elif os.path.exists(".env.example"):
        with open(".env.example", "r", encoding="utf-8") as f:
            env_lines = f.readlines()

    def set_env_var(lines, key, val):
        if not val:
            return lines
        found = False
        new_lines = []
        for line in lines:
            if line.startswith(f"{key}=") or line.startswith(f"#{key}="):
                new_lines.append(f"{key}={val}\n")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={val}\n")
        return new_lines

    env_lines = set_env_var(env_lines, "LEADSWEEP_ADMIN_EMAIL", email)
    env_lines = set_env_var(env_lines, "LEADSWEEP_ADMIN_PASSWORD", pwd)
    env_lines = set_env_var(env_lines, "LEADSWEEP_ADMIN_NAME", name)
    if groq_api:
        env_lines = set_env_var(env_lines, "GROQ_API_KEY", groq_api)
    if gemini_api:
        env_lines = set_env_var(env_lines, "GEMINI_API_KEY", gemini_api)
    
    with open(".env", "w", encoding="utf-8") as f:
        f.writelines(env_lines)

    # 2. Setup SQLite admin user
    os.makedirs("data", exist_ok=True)
    db_path = os.path.join("data", "leadsweep.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Ensure table exists
    c.execute("""
        CREATE TABLE IF NOT EXISTS app_users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            plan TEXT NOT NULL DEFAULT 'Enterprise Admin',
            created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'approved',
            credits INTEGER NOT NULL DEFAULT 999999,
            early_access_status TEXT NOT NULL DEFAULT 'approved',
            company TEXT DEFAULT 'Enterprise',
            plain_password TEXT
        )
    """)

    pwd_hash = hashlib.sha256(pwd.encode("utf-8")).hexdigest()
    user_id = f"usr_{hashlib.md5(email.encode('utf-8')).hexdigest()[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    c.execute("""
        INSERT INTO app_users (id, email, name, password_hash, role, plan, created_at, status, credits, early_access_status, company, plain_password)
        VALUES (?, ?, ?, ?, 'owner', 'Enterprise Owner', ?, 'approved', 999999, 'approved', 'Enterprise Admin', ?)
        ON CONFLICT(email) DO UPDATE SET
            password_hash=excluded.password_hash,
            role='owner',
            plan='Enterprise Owner',
            credits=999999,
            status='approved',
            early_access_status='approved',
            plain_password=excluded.plain_password
    """, (user_id, email, name, pwd_hash, now_iso, pwd))

    conn.commit()
    conn.close()

    # 3. Setup X session if provided
    if twitter_auth:
        import json
        session_data = {
            "auth_token": twitter_auth,
            "ct0": twitter_ct0 or ""
        }
        with open("sessions.json", "w", encoding="utf-8") as sf:
            json.dump({"default": session_data, "admin": session_data, email: session_data}, sf, indent=2)

    with open(".setup_done", "w", encoding="utf-8") as f:
        f.write(f"Admin configured for {email} on {now_iso}\n")

    print("\n[SUCCESS] Admin account created successfully with UNLIMITED credits!")
    print(f"Login Email:    {email}")
    print(f"Role / Plan:    owner / Enterprise Owner (Unlimited Credits)")
    print("=====================================================\n")

if __name__ == "__main__":
    setup_admin()

