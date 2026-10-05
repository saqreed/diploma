"""Verify the real local HTTPS entry, certificate validation and session protection."""
import argparse
import json
import re
import socket
import ssl
from pathlib import Path

import httpx2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ca", required=True)
    parser.add_argument("--env-file", default="../.env")
    options = parser.parse_args()
    values = dict(line.split("=", 1) for line in Path(options.env_file).read_text(encoding="utf-8-sig").splitlines() if "=" in line and not line.startswith("#"))
    context = ssl.create_default_context(cafile=options.ca)
    with socket.create_connection(("127.0.0.1", 8443), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname="localhost") as encrypted:
            tls_version = encrypted.version()
            assert tls_version in {"TLSv1.2", "TLSv1.3"}
    with httpx2.Client(base_url="https://localhost:8443", verify=context, trust_env=False, timeout=15) as client:
        assert client.get("/health").json() == {"status": "ok"}
        html = client.get("/login").text
        assert "<html" in html.lower()
        assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
        assert assets, "Production assets were not referenced"
        for asset in assets:
            assert client.get(asset).status_code == 200
        response = client.post("/api/auth/login", headers={"X-Requested-With": "antifraud-ui"}, json={"username": "admin", "password": values["DIPLOMA_SEED_PASSWORD"]})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
        assert client.get("/api/auth/me").status_code == 200
        assert client.get("/api/admin/applications").status_code == 200
        assert client.get("http://localhost:8000/api/auth/me").status_code == 401
        assert client.post("/api/auth/logout", headers={"X-Requested-With": "antifraud-ui"}).status_code == 200
        assert client.get("/api/auth/me").status_code == 401
    with httpx2.Client(verify=context, trust_env=False, timeout=15) as client:
        assert client.get("https://127.0.0.1:8443/health").status_code == 200
    try:
        with socket.create_connection(("127.0.0.1", 8443), timeout=15) as raw:
            with ssl.create_default_context().wrap_socket(raw, server_hostname="localhost"):
                pass
    except ssl.SSLCertVerificationError:
        pass
    else:
        raise AssertionError("Private CA unexpectedly trusted by the default client")
    try:
        with socket.create_connection(("127.0.0.1", 8443), timeout=15) as raw:
            with context.wrap_socket(raw, server_hostname="wrong-host.invalid"):
                pass
    except ssl.SSLError:
        pass
    else:
        raise AssertionError("Wrong hostname unexpectedly accepted")
    print(json.dumps({"https": "PASS", "tls_version": tls_version, "certificate_and_hostname_validation": True, "untrusted_ca_and_wrong_hostname_rejected": True, "production_assets_available": True, "secure_httponly_samesite_cookie": True, "secure_cookie_not_sent_over_http": True, "real_login_roles_logout": True, "os_trust_store_changed": False}))


if __name__ == "__main__":
    main()
