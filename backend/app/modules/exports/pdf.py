"""Print-ready ReportLab PDF renderer for HandoffScope Tamper-Evident Handover Certificates."""

from __future__ import annotations

import io
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Corporate palette matching Section 3.5
_CHARCOAL_GREEN = colors.HexColor("#26332F")
_EUCALYPTUS = colors.HexColor("#527568")
_SOFT_MINT = colors.HexColor("#E3EEE8")
_ROW_ALT = colors.HexColor("#F3F4F1")
_BORDER = colors.HexColor("#CFD7CE")
_TEXT_PRIMARY = colors.HexColor("#202A27")
_TEXT_SECONDARY = colors.HexColor("#596760")
_WARNING_BG = colors.HexColor("#FDF3E7")
_WARNING_FG = colors.HexColor("#8A5416")
_ERROR_FG = colors.HexColor("#9A3A3A")


def _p(text: Any, style: ParagraphStyle, max_len: int = 1200) -> Paragraph:
    raw = str(text if text is not None else "—")
    if len(raw) > max_len:
        raw = raw[:max_len] + " … [truncated]"
    safe = escape(raw).replace("\n", "<br/>")
    return Paragraph(safe, style)


def _draw_page_chrome(canvas, doc, *, title: str, footer_text: str) -> None:
    canvas.saveState()
    width, height = LETTER
    # Subtle top accent rule
    canvas.setStrokeColor(_EUCALYPTUS)
    canvas.setLineWidth(1.5)
    canvas.line(0.6 * inch, height - 0.48 * inch, width - 0.6 * inch, height - 0.48 * inch)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(_TEXT_SECONDARY)
    canvas.drawString(0.6 * inch, height - 0.40 * inch, title[:95])

    # Footer
    canvas.setStrokeColor(_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(0.6 * inch, 0.55 * inch, width - 0.6 * inch, 0.55 * inch)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(_TEXT_SECONDARY)
    canvas.drawString(0.6 * inch, 0.40 * inch, footer_text[:100])
    canvas.drawRightString(width - 0.6 * inch, 0.40 * inch, f"Page {doc.page}")
    canvas.restoreState()


def render_handover_certificate_pdf(
    *,
    projection: dict[str, Any],
    signer_info: dict[str, Any],
) -> bytes:
    """Render a structured, tamper-evident PDF certificate from clearance-filtered data."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.72 * inch,
        title=f"HandoffScope Handover Certificate - {projection['case_title']}",
        author="HandoffScope",
        invariant=1,
    )

    base = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "HS_Title",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        textColor=colors.white,
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "HS_Subtitle",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#DFE6E1"),
    )
    h2_style = ParagraphStyle(
        "HS_H2",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=15,
        textColor=_CHARCOAL_GREEN,
        spaceBefore=12,
        spaceAfter=5,
    )
    body_style = ParagraphStyle(
        "HS_Body",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=_TEXT_PRIMARY,
    )
    small_style = ParagraphStyle(
        "HS_Small",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10.5,
        textColor=_TEXT_SECONDARY,
    )
    mono_style = ParagraphStyle(
        "HS_Mono",
        parent=base["Normal"],
        fontName="Courier",
        fontSize=7.5,
        leading=10,
        textColor=_TEXT_PRIMARY,
    )
    table_hdr_style = ParagraphStyle(
        "HS_TblHdr",
        parent=base["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )

    usable_w = LETTER[0] - 1.2 * inch
    story: list[Any] = []

    # 1. Certificate Header Banner
    banner_tbl = Table(
        [
            [
                _p("HandoffScope — Tamper-Evident Handover Certificate", title_style),
            ],
            [
                _p(
                    f"Project: {projection['project_name']}  |  Case #{projection['case_number']}: "
                    f"{projection['case_title']}  |  Approved Version v{projection['version_number']}",
                    subtitle_style,
                )
            ],
        ],
        colWidths=[usable_w],
    )
    banner_tbl.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _CHARCOAL_GREEN),
            ("TOPPADDING", (0, 0), (-1, 0), 12),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ])
    )
    story.append(banner_tbl)
    story.append(Spacer(1, 10))

    # 2. Scope, Version Metadata & Digest
    story.append(_p("1. Version Metadata & Export Attestation Scope", h2_style))
    meta_rows = [
        [_p("Case ID", body_style), _p(projection["case_id"], mono_style)],
        [_p("Handover Version ID", body_style), _p(f"{projection['version_id']} (v{projection['version_number']})", mono_style)],
        [_p("Lifecycle / Sync State", body_style), _p(f"{projection['case_status']} / {projection['sync_status']}", body_style)],
        [_p("Export Clearance Scope", body_style), _p(projection["export_scope"], body_style)],
        [_p("Exported By", body_style), _p(f"{projection['exported_by_name']} ({projection['exported_by_email']})", body_style)],
        [_p("Approved By & At", body_style), _p(f"{projection['approved_by_name']} — {projection['approved_at']}", body_style)],
        [_p("Snapshot SHA-256 Digest", body_style), _p(projection["snapshot_hash"], mono_style)],
        [_p("Generated At (UTC)", body_style), _p(f"{projection['generated_at']} (Format v{projection['format_version']})", body_style)],
    ]
    meta_tbl = Table(meta_rows, colWidths=[1.8 * inch, usable_w - 1.8 * inch])
    meta_tbl.setStyle(
        TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, _BORDER),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, _ROW_ALT]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(meta_tbl)

    # 3. Restricted Evidence Notice
    redacted_count = projection.get("redacted_claims_count", 0)
    if projection["export_scope"] != "INTERNAL_FULL" or redacted_count > 0:
        story.append(Spacer(1, 8))
        notice = (
            f"Restricted Evidence Notice: {redacted_count} claim(s) referencing elevated-clearance sources "
            "were withheld prior to hashing and PDF generation in accordance with viewer access policy."
            if redacted_count > 0
            else "Restricted Evidence Notice: Export generated under recipient-safe projection policy."
        )
        notice_tbl = Table([[_p(notice, ParagraphStyle("HS_Warn", parent=body_style, textColor=_WARNING_FG))]], colWidths=[usable_w])
        notice_tbl.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), _WARNING_BG),
                ("BOX", (0, 0), (-1, -1), 0.75, _WARNING_FG),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
        )
        story.append(notice_tbl)

    # 4. Executive Summary
    story.append(_p("2. Executive Handover Summary", h2_style))
    summary = projection["summary"]
    story.append(
        _p(
            f"Transfer Packs: {summary['total_packs']}  |  Total Claims: {summary['total_claims']}  |  "
            f"Knowledge Gaps / Risks: {summary['total_gaps']}  |  Next Actions: {summary['total_next_actions']}  |  "
            f"Amendment Note: {projection.get('amendment_reason') or 'Initial approved baseline'}",
            body_style,
        )
    )

    # 5. Transfer Pack Inventory & Claim Verification Matrix
    story.append(_p("3. Transfer Pack Inventory & Claim Verification Matrix", h2_style))
    packs = projection.get("transfer_packs", [])
    if not packs:
        story.append(_p("No transfer packs recorded in this snapshot.", small_style))
    else:
        pack_rows = [[
            _p("Transfer Pack", table_hdr_style),
            _p("Component Area", table_hdr_style),
            _p("Claims", table_hdr_style),
            _p("Status", table_hdr_style),
        ]]
        for p in packs:
            pack_rows.append([
                _p(p.get("name"), body_style),
                _p(p.get("component_area") or "General", body_style),
                _p(str(len(p.get("claims", []))), body_style),
                _p(p.get("status") or "READY", body_style),
            ])
        ptbl = LongTable(pack_rows, colWidths=[2.6 * inch, 1.8 * inch, 0.9 * inch, usable_w - 5.3 * inch], repeatRows=1)
        ptbl.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), _EUCALYPTUS),
                ("GRID", (0, 0), (-1, -1), 0.5, _BORDER),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(ptbl)
        story.append(Spacer(1, 8))

        claim_rows = [[
            _p("Pack / Claim Title", table_hdr_style),
            _p("Type", table_hdr_style),
            _p("Evidence / Review", table_hdr_style),
            _p("Content & Citation Locators", table_hdr_style),
        ]]
        for p in packs:
            for c in p.get("claims", []):
                ev_locs = [
                    ev.get("locator") or ev.get("evidence_type") or "Evidence"
                    for ev in (c.get("evidence") or [])
                    if isinstance(ev, dict)
                ]
                loc_str = ", ".join(ev_locs[:4]) if ev_locs else "No attached citations"
                claim_rows.append([
                    _p(f"[{p.get('name')}] {c.get('title')}", body_style, 250),
                    _p(c.get("claim_type"), small_style),
                    _p(f"{c.get('evidence_state')}\n({c.get('review_state')})", small_style),
                    _p(f"{c.get('body_text') or ''}\nCitations: {loc_str}", small_style, 450),
                ])

        if len(claim_rows) > 1:
            ctbl = LongTable(
                claim_rows,
                colWidths=[1.85 * inch, 0.95 * inch, 1.25 * inch, usable_w - 4.05 * inch],
                repeatRows=1,
            )
            ctbl.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), _CHARCOAL_GREEN),
                    ("GRID", (0, 0), (-1, -1), 0.5, _BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ])
            )
            story.append(ctbl)

    # 6. Outstanding Items / Knowledge Gaps
    story.append(_p("4. Unfinished Work & Knowledge Gaps", h2_style))
    unfinished = projection.get("unfinished_items", [])
    if not unfinished:
        story.append(_p("No unresolved knowledge gaps or risks captured in this version.", small_style))
    else:
        for idx, item in enumerate(unfinished[:40], 1):
            story.append(
                _p(
                    f"{idx}. [{item.get('priority', 'MEDIUM')}] {item.get('title')}: "
                    f"{item.get('description') or ''}",
                    small_style,
                    400,
                )
            )

    # 7. Approval Override Attestation (when Lead Override was used)
    override_meta = projection.get("override_metadata")
    overridden_items = projection.get("overridden_unresolved_items") or []
    story.append(_p("5. Approval & Override Attestation", h2_style))
    if override_meta:
        story.append(
            _p(
                f"Lead Override Applied by {override_meta.get('override_by_name') or 'Project Lead'} "
                f"at {override_meta.get('override_at') or projection['approved_at']} — "
                f"Justification: {override_meta.get('override_justification') or 'Provided'}",
                ParagraphStyle("HS_Ovr", parent=body_style, textColor=_ERROR_FG),
            )
        )
        for ov in overridden_items[:20]:
            story.append(_p(f"- Overridden Blocker: {ov.get('message') or ov}", small_style))
    else:
        story.append(_p("Approved cleanly with zero overridden blockers.", body_style))

    # 8. Successor Acknowledgements & Responsibility Ledger (Export-Time Dated Attestation)
    story.append(_p("6. Successor Acknowledgements & Ownership Ledger (Export-Time Attestation)", h2_style))
    story.append(
        _p(
            f"Attestation state captured at export timestamp {projection['generated_at']} "
            f"for Version v{projection['version_number']}.",
            small_style,
        )
    )
    acks = projection.get("acknowledgements", [])
    assignments = projection.get("responsibility_assignments", [])
    if acks:
        for a in acks:
            story.append(
                _p(
                    f"Acknowledgement: {a.get('user_name')} ({a.get('user_email')}) "
                    f"acknowledged receipt at {a.get('acknowledged_at')}",
                    small_style,
                )
            )
    else:
        story.append(_p("No formal recipient receipt acknowledgements recorded at export time.", small_style))

    if assignments:
        asgn_rows = [[
            _p("Transfer Pack", table_hdr_style),
            _p("Assigned Engineer", table_hdr_style),
            _p("Decision", table_hdr_style),
            _p("Responded At / Note", table_hdr_style),
        ]]
        for r in assignments:
            asgn_rows.append([
                _p(r.get("transfer_pack_name"), body_style),
                _p(r.get("assignee_name"), body_style),
                _p(r.get("status"), body_style),
                _p(f"{r.get('responded_at') or 'Pending'}\n{r.get('decline_reason') or ''}", small_style, 260),
            ])
        atbl = LongTable(asgn_rows, colWidths=[2.0 * inch, 1.5 * inch, 1.3 * inch, usable_w - 4.8 * inch], repeatRows=1)
        atbl.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), _EUCALYPTUS),
                ("GRID", (0, 0), (-1, -1), 0.5, _BORDER),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT]),
                ("PADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(Spacer(1, 4))
        story.append(atbl)

    # 9. Cryptographic Verification Metadata
    story.append(_p("7. Cryptographic Signing & Verification Identity", h2_style))
    story.append(
        _p(
            f"Algorithm: {signer_info['algorithm']}  |  Key ID: {signer_info['signing_key_id']}  |  "
            f"Persistent Signing Key: {'Yes' if signer_info['persistent_key_configured'] else 'Ephemeral/Local'}",
            small_style,
        )
    )
    story.append(_p(f"Public Key Fingerprint: {signer_info['public_key_fingerprint']}", mono_style))
    story.append(
        _p(
            "Verification note: Verify offline bundles with verify_bundle.py or POST /api/v1/exports/verify. "
            "Compare the fingerprint above against /api/v1/exports/signing-key to confirm trusted signer identity.",
            small_style,
        )
    )

    header_title = f"HandoffScope Compliance Certificate — {projection['project_name']} (v{projection['version_number']})"
    footer_meta = f"Key ID: {signer_info['signing_key_id']} | Scope: {projection['export_scope']}"
    doc.build(
        story,
        onFirstPage=lambda c, d: _draw_page_chrome(c, d, title=header_title, footer_text=footer_meta),
        onLaterPages=lambda c, d: _draw_page_chrome(c, d, title=header_title, footer_text=footer_meta),
    )
    return buf.getvalue()
