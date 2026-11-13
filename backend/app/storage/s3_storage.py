"""S3-compatible / Cloudflare R2 storage backend using pure-Python AWS Signature v4 over httpx."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from app.storage.base import StorageBackend

logger = logging.getLogger("handoffscope.storage.s3")


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str, service: str = "s3") -> bytes:
    k_date = _sign(f"AWS4{secret_key}".encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


class S3CompatibleStorageBackend(StorageBackend):
    """Stores private document blobs in Cloudflare R2 or any S3-compatible object store."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ):
        clean_ep = (endpoint_url or "").strip().rstrip("/")
        if not clean_ep or not bucket or not access_key_id or not secret_access_key:
            raise ValueError("S3/R2 configuration incomplete (endpoint_url, bucket, keys required)")
        self.endpoint_url = clean_ep
        self.bucket = bucket.strip()
        self.access_key_id = access_key_id.strip()
        self.secret_access_key = secret_access_key.strip()
        self.region = (region or "auto").strip()
        parsed = urlparse(self.endpoint_url)
        self.host = parsed.netloc
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def _signed_request(
        self,
        method: str,
        key: str,
        *,
        body: bytes = b"",
        content_type: str | None = None,
    ) -> httpx.Response:
        clean_key = key.replace("\\", "/").lstrip("/")
        parts = clean_key.split("/")
        if ".." in parts or any(p in ("..", "%2e%2e", "%2E%2E") for p in parts):
            raise ValueError("Path traversal detected")
        canonical_uri = "/" + quote(f"{self.bucket}/{clean_key}", safe="/-_.~")
        url = f"{self.endpoint_url}{canonical_uri}"

        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(body).hexdigest()

        headers_to_sign = {
            "host": self.host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        clean_ct = content_type.strip() if content_type else None
        if clean_ct and method in ("PUT", "POST"):
            headers_to_sign["content-type"] = clean_ct

        sorted_keys = sorted(headers_to_sign.keys())
        canonical_headers = "".join(f"{k}:{headers_to_sign[k]}\n" for k in sorted_keys)
        signed_headers = ";".join(sorted_keys)

        canonical_request = "\n".join([
            method,
            canonical_uri,
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        ])
        scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ])
        sig_key = _signing_key(self.secret_access_key, date_stamp, self.region)
        signature = hmac.new(sig_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        auth_header = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        req_headers = {
            "Authorization": auth_header,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if clean_ct and method in ("PUT", "POST"):
            req_headers["Content-Type"] = clean_ct

        return self._client.request(method, url, headers=req_headers, content=body if method in ("PUT", "POST") else None)

    def save(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        resp = self._signed_request("PUT", path, body=data, content_type=content_type)
        if resp.status_code >= 400:
            raise RuntimeError(f"S3/R2 upload failed (HTTP {resp.status_code})")
        logger.info("Saved object to S3/R2: %s (%d bytes)", path, len(data))
        return f"s3://{self.bucket}/{path.lstrip('/')}"

    def _extract_key(self, path: str) -> str:
        clean = path.replace("\\", "/")
        prefix = f"s3://{self.bucket}/"
        if clean.startswith(prefix):
            return clean[len(prefix) :]
        if clean.startswith("s3://"):
            # Strip arbitrary s3://bucket/ prefix cleanly
            parts = clean[5:].split("/", 1)
            return parts[1] if len(parts) == 2 else ""
        return clean.lstrip("/")

    def load(self, path: str) -> bytes:
        key = self._extract_key(path)
        resp = self._signed_request("GET", key)
        if resp.status_code == 404:
            raise FileNotFoundError(f"Object not found in S3/R2: {key}")
        if resp.status_code >= 400:
            raise RuntimeError(f"S3/R2 read failed (HTTP {resp.status_code})")
        return resp.content

    def delete(self, path: str) -> bool:
        key = self._extract_key(path)
        resp = self._signed_request("DELETE", key)
        if resp.status_code == 404:
            return False
        if resp.status_code >= 400:
            raise RuntimeError(f"S3/R2 delete failed (HTTP {resp.status_code})")
        return True

    def exists(self, path: str) -> bool:
        key = self._extract_key(path)
        resp = self._signed_request("HEAD", key)
        return resp.status_code == 200

    def get_url(self, path: str) -> str:
        # Never expose direct bucket URLs that bypass HandoffScope backend RBAC
        return f"/api/v1/documents/by-key"
