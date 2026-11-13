"""Safe ZIP inspection, cryptographic bundle verification, and standalone offline verifier generator."""

from __future__ import annotations

import io
import json
import posixpath
import zipfile
from typing import Iterable

from app.modules.exports.crypto import (
    get_trusted_fingerprints,
    sha256_hex,
    verify_ed25519_signature,
)
from app.modules.exports.schemas import ExportVerificationResultOut

MAX_ZIP_ENTRIES = 200
MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 25 * 1024 * 1024  # 25 MB
MAX_ZIP_COMPRESSION_RATIO = 100
CONTROL_FILES = {"manifest.json", "certificate.sig", "public_key.pem"}


def _is_safe_archive_path(raw_name: str) -> bool:
    if not raw_name or raw_name.startswith("/") or raw_name.startswith("\\"):
        return False
    if "\\" in raw_name or "\x00" in raw_name:
        return False
    norm = posixpath.normpath(raw_name)
    if norm in (".", "..") or norm.startswith("../") or "/../" in norm:
        return False
    return True


def verify_compliance_bundle_bytes(
    zip_bytes: bytes,
    *,
    trusted_fingerprints: Iterable[str] | None = None,
) -> ExportVerificationResultOut:
    """Safely inspect a compliance ZIP bundle without disk extraction and verify integrity + signature."""
    errors: list[str] = []
    failed_artifacts: list[str] = []
    missing_artifacts: list[str] = []
    unexpected_entries: list[str] = []

    if len(zip_bytes) > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
        return ExportVerificationResultOut(
            overall_status="MALFORMED",
            integrity_valid=False,
            signature_valid=False,
            trusted_signer_verified=False,
            errors=["Uploaded archive exceeds maximum allowed size"],
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r")
    except zipfile.BadZipFile:
        return ExportVerificationResultOut(
            overall_status="MALFORMED",
            integrity_valid=False,
            signature_valid=False,
            trusted_signer_verified=False,
            errors=["File is not a valid ZIP archive"],
        )

    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            return ExportVerificationResultOut(
                overall_status="MALFORMED",
                integrity_valid=False,
                signature_valid=False,
                trusted_signer_verified=False,
                errors=[f"Archive contains too many entries ({len(infos)} > {MAX_ZIP_ENTRIES})"],
            )

        seen_names: set[str] = set()
        total_uncompressed = 0
        for info in infos:
            if info.is_dir():
                continue
            if not _is_safe_archive_path(info.filename):
                return ExportVerificationResultOut(
                    overall_status="MALFORMED",
                    integrity_valid=False,
                    signature_valid=False,
                    trusted_signer_verified=False,
                    errors=[f"Unsafe archive entry path detected: {info.filename}"],
                )
            if info.filename in seen_names:
                return ExportVerificationResultOut(
                    overall_status="MALFORMED",
                    integrity_valid=False,
                    signature_valid=False,
                    trusted_signer_verified=False,
                    errors=[f"Duplicate archive entry detected: {info.filename}"],
                )
            seen_names.add(info.filename)
            total_uncompressed += max(info.file_size, 0)
            if total_uncompressed > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
                return ExportVerificationResultOut(
                    overall_status="MALFORMED",
                    integrity_valid=False,
                    signature_valid=False,
                    trusted_signer_verified=False,
                    errors=["Decompressed archive size exceeds safety limit"],
                )
            if info.compress_size > 0 and (info.file_size / info.compress_size) > MAX_ZIP_COMPRESSION_RATIO:
                return ExportVerificationResultOut(
                    overall_status="MALFORMED",
                    integrity_valid=False,
                    signature_valid=False,
                    trusted_signer_verified=False,
                    errors=[f"Suspicious compression ratio on entry: {info.filename}"],
                )

        for req in CONTROL_FILES:
            if req not in seen_names:
                missing_artifacts.append(req)
        if missing_artifacts:
            return ExportVerificationResultOut(
                overall_status="MALFORMED",
                integrity_valid=False,
                signature_valid=False,
                trusted_signer_verified=False,
                missing_artifacts=missing_artifacts,
                errors=[f"Missing required verification file(s): {', '.join(missing_artifacts)}"],
            )

        try:
            manifest_bytes = zf.read("manifest.json")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except Exception as exc:
            return ExportVerificationResultOut(
                overall_status="MALFORMED",
                integrity_valid=False,
                signature_valid=False,
                trusted_signer_verified=False,
                errors=[f"Failed to parse manifest.json: {exc}"],
            )

        try:
            sig_env = json.loads(zf.read("certificate.sig").decode("utf-8"))
            pub_pem = zf.read("public_key.pem")
        except Exception as exc:
            return ExportVerificationResultOut(
                overall_status="MALFORMED",
                integrity_valid=False,
                signature_valid=False,
                trusted_signer_verified=False,
                errors=[f"Failed to parse signature material: {exc}"],
            )

        if manifest.get("format") != "handoffscope-compliance-bundle":
            return ExportVerificationResultOut(
                overall_status="MALFORMED",
                integrity_valid=False,
                signature_valid=False,
                trusted_signer_verified=False,
                errors=["Unsupported or unrecognized bundle format identifier"],
            )

        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            return ExportVerificationResultOut(
                overall_status="MALFORMED",
                integrity_valid=False,
                signature_valid=False,
                trusted_signer_verified=False,
                errors=["manifest.json contains no artifact entries"],
            )

        manifest_paths: set[str] = set()
        for entry in artifacts:
            if not isinstance(entry, dict) or not entry.get("path"):
                errors.append("Malformed artifact record in manifest.json")
                continue
            path = str(entry["path"])
            manifest_paths.add(path)
            if path not in seen_names:
                missing_artifacts.append(path)
                continue
            actual_bytes = zf.read(path)
            if len(actual_bytes) != entry.get("size_bytes"):
                failed_artifacts.append(path)
                errors.append(f"Byte length mismatch for {path}")
                continue
            if sha256_hex(actual_bytes) != entry.get("sha256"):
                failed_artifacts.append(path)
                errors.append(f"SHA-256 digest mismatch for {path}")

        for entry_name in sorted(seen_names - CONTROL_FILES - manifest_paths):
            unexpected_entries.append(entry_name)
            errors.append(f"Unexpected unsigned file inside archive: {entry_name}")

        integrity_valid = not (failed_artifacts or missing_artifacts or unexpected_entries or errors)

        sig_valid, key_fp, sig_err = verify_ed25519_signature(
            public_key_pem=pub_pem,
            manifest_bytes=manifest_bytes,
            signature_envelope=sig_env,
        )
        if sig_err:
            errors.append(sig_err)

        trusted_set = set(trusted_fingerprints) if trusted_fingerprints is not None else get_trusted_fingerprints()
        trusted_signer_verified = bool(sig_valid and key_fp and key_fp in trusted_set)

        if not integrity_valid:
            overall = "TAMPERED"
        elif not sig_valid:
            overall = "INVALID_SIGNATURE"
        elif trusted_signer_verified:
            overall = "VALID"
        else:
            overall = "VALID_UNTRUSTED_SIGNER"

        return ExportVerificationResultOut(
            overall_status=overall,
            integrity_valid=integrity_valid,
            signature_valid=sig_valid,
            trusted_signer_verified=trusted_signer_verified,
            case_id=str(manifest.get("case_id") or "") or None,
            handover_version_id=str(manifest.get("handover_version_id") or "") or None,
            handover_version_number=manifest.get("handover_version_number"),
            export_scope=manifest.get("export_scope"),
            signing_key_id=sig_env.get("signing_key_id") or manifest.get("signing_key_id"),
            public_key_fingerprint=key_fp,
            artifacts_checked=len(artifacts),
            failed_artifacts=failed_artifacts,
            missing_artifacts=missing_artifacts,
            unexpected_entries=unexpected_entries,
            errors=errors,
        )


STANDALONE_VERIFY_SCRIPT = '''#!/usr/bin/env python3
"""Standalone offline verifier for HandoffScope compliance bundles (zero server required)."""

import base64
import hashlib
import json
import sys
import zipfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def verify_bundle(zip_path: str, expected_fingerprint: str | None = None) -> int:
    with zipfile.ZipFile(zip_path, "r") as zf:
        manifest_bytes = zf.read("manifest.json")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        sig_env = json.loads(zf.read("certificate.sig").decode("utf-8"))
        pub_pem = zf.read("public_key.pem")

        pub = serialization.load_pem_public_key(pub_pem)
        if not isinstance(pub, Ed25519PublicKey):
            print("FAIL: public_key.pem is not an Ed25519 key")
            return 2

        spki_der = pub.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        fingerprint = "SHA256:" + hashlib.sha256(spki_der).hexdigest()

        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        if sig_env.get("manifest_sha256") != manifest_sha:
            print("TAMPERED: manifest.json digest does not match certificate.sig")
            return 1

        try:
            pub.verify(base64.b64decode(sig_env["signature_b64"]), manifest_bytes)
            print(f"SIGNATURE VALID (Key ID: {sig_env.get('signing_key_id')}, Fingerprint: {fingerprint})")
        except Exception as exc:
            print(f"INVALID SIGNATURE: {exc}")
            return 1

        listed = set()
        for art in manifest.get("artifacts", []):
            path = art["path"]
            listed.add(path)
            data = zf.read(path)
            if len(data) != art["size_bytes"] or hashlib.sha256(data).hexdigest() != art["sha256"]:
                print(f"TAMPERED: Artifact failed hash/size check -> {path}")
                return 1

        extras = set(zf.namelist()) - listed - {"manifest.json", "certificate.sig", "public_key.pem"}
        if extras:
            print(f"TAMPERED: Unexpected unsigned entries -> {sorted(extras)}")
            return 1

        print(f"INTEGRITY VALID: All {len(listed)} manifest artifacts verified.")
        if expected_fingerprint:
            if expected_fingerprint.strip() == fingerprint:
                print("TRUSTED SIGNER VERIFIED: Public key fingerprint matches supplied trusted fingerprint.")
            else:
                print(f"WARNING: Trusted fingerprint mismatch (expected {expected_fingerprint}, got {fingerprint})")
                return 3
        else:
            print("NOTE: Bundle is self-consistent, but compare public_key_fingerprint against your HandoffScope server to confirm trusted signer identity.")
        return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python verify_bundle.py <compliance-bundle.zip> [expected_fingerprint]")
        sys.exit(2)
    sys.exit(verify_bundle(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
'''
