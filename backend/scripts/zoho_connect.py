"""
Connect Zoho Books, once, on the server.

1. api-console.zoho.in -> Add Client -> Self Client. Put its Client ID and
   Client Secret in backend/.env as ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET, and
   ZOHO_ORG_ID=<organisation id>.
2. In the Self Client's "Generate Code" tab, scope:
     ZohoBooks.contacts.ALL,ZohoBooks.invoices.ALL,ZohoBooks.customerpayments.READ,ZohoBooks.settings.READ
   duration 10 minutes. Put the code in backend/.env as ZOHO_GRANT_CODE=...
3. Within 10 minutes run:  venv/bin/python scripts/zoho_connect.py

It swaps the code for a refresh token, writes ZOHO_REFRESH_TOKEN into .env,
removes ZOHO_GRANT_CODE, and checks the connection by reading the
organisation's name. It prints no secret.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(HERE, ".env")
sys.path.insert(0, HERE)


def _set_env_line(text: str, key: str, value):
    lines = [l for l in text.splitlines() if not re.match(rf"^{key}=", l)]
    if value is not None:
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH, override=True)
    code = (os.getenv("ZOHO_GRANT_CODE") or (sys.argv[1] if len(sys.argv) > 1 else "")).strip()
    from integrations import zoho_books as zb
    missing = [n for n in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_ORG_ID") if not os.getenv(n)]
    if missing:
        print("Missing in .env:", ", ".join(missing))
        return 1
    if not os.getenv("ZOHO_REFRESH_TOKEN"):
        if not code:
            print("No ZOHO_GRANT_CODE in .env (generate one; it expires in 10 minutes).")
            return 1
        data = zb.exchange_grant_code(code)
        text = open(ENV_PATH, encoding="utf-8").read()
        text = _set_env_line(text, "ZOHO_REFRESH_TOKEN", data["refresh_token"])
        text = _set_env_line(text, "ZOHO_GRANT_CODE", None)
        open(ENV_PATH, "w", encoding="utf-8").write(text)
        os.environ["ZOHO_REFRESH_TOKEN"] = data["refresh_token"]
        print("Refresh token saved to .env; grant code removed.")
    org = zb.organization()
    print("Connected to Zoho Books:", org.get("name"), "| currency", org.get("currency_code"),
          "| GST registered", bool(org.get("tax_reg_no") or org.get("gst_no")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
