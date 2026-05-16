#!/usr/bin/env python3
"""Auto-generate security checklist based on codebase scan."""
import json, os, re, sys
from pathlib import Path

def scan_patterns():
    """Scan for security-relevant patterns in codebase."""
    findings = []
    cwd = Path(".")

    # Detect patterns
    patterns = {
        "authentication": r"(password|login|auth|session|jwt|token)",
        "database": r"(sql|query|SELECT|INSERT|UPDATE|DELETE|prisma|sequelize|knex)",
        "api": r"(api|endpoint|route|controller|express|fastapi|flask)",
        "encryption": r"(encrypt|decrypt|hash|bcrypt|crypto|aes)",
        "file_upload": r"(upload|multipart|formdata|file.*input)",
        "environment": r"(process\.env|os\.environ|dotenv|\.env)",
    }

    for ext in ["*.py", "*.js", "*.ts", "*.tsx", "*.jsx"]:
        for f in cwd.rglob(ext):
            if ".git" in str(f) or "node_modules" in str(f) or ".taskmaster" in str(f):
                continue
            try:
                content = f.read_text(errors="ignore")
                for category, pattern in patterns.items():
                    if re.search(pattern, content, re.IGNORECASE):
                        findings.append({"file": str(f), "category": category})
            except Exception:
                pass

    categories = list(set(f["category"] for f in findings))

    checklist = []
    if "authentication" in categories:
        checklist.extend([
            "Passwords hashed with bcrypt (cost >= 10)",
            "Session tokens cryptographically secure",
            "Rate limiting on auth endpoints",
        ])
    if "database" in categories:
        checklist.extend([
            "All queries use parameterized statements",
            "No SQL injection vulnerabilities",
            "Database credentials not in source code",
        ])
    if "api" in categories:
        checklist.extend([
            "HTTPS enforced in production",
            "CSRF protection enabled",
            "Input validation on all endpoints",
            "Security headers set (CSP, X-Frame-Options)",
        ])
    if "encryption" in categories:
        checklist.extend([
            "Strong encryption algorithms used (AES-256)",
            "Keys stored securely (not hardcoded)",
        ])
    if "environment" in categories:
        checklist.extend([
            ".env files in .gitignore",
            "No secrets committed to repository",
        ])

    # Always include
    checklist.extend([
        "Dependencies checked for vulnerabilities (npm audit / pip audit)",
        "Error messages do not leak internal details",
    ])

    print(json.dumps({
        "ok": True,
        "categories_detected": categories,
        "findings_count": len(findings),
        "checklist": checklist,
    }, indent=2))

if __name__ == "__main__":
    scan_patterns()
