"""Shared, email-client-safe layout for Aspirova notification emails."""

from html import escape
from html.parser import HTMLParser

from core.config import get_settings


class _IntroTextParser(HTMLParser):
    """Extract visible text for the inbox-preview preheader."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _site_url() -> str:
    return get_settings().site_url.rstrip("/")


def _preheader_text(intro_html: str) -> str:
    parser = _IntroTextParser()
    parser.feed(intro_html)
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def text_footer() -> str:
    """Return the shared plain-text footer for multipart email alternatives."""

    return "\n".join(
        [
            "You're receiving this because you use Aspirova.",
            f"Manage email preferences: {_site_url()}/account?section=notifications",
            "Opportunities are gathered from public sources and can change — "
            "always confirm details on the official page.",
            "Aspirova — every opportunity, one place.",
        ]
    )


def email_layout(
    *,
    title: str,
    intro_html: str,
    body_html: str,
    cta_label: str | None = None,
    cta_url: str | None = None,
    footer_note: str | None = None,
) -> str:
    """Wrap trusted, already-escaped content blocks in the shared email shell."""

    site_url = _site_url()
    preference_url = escape(f"{site_url}/account?section=notifications", quote=True)
    preheader = escape(_preheader_text(intro_html), quote=True)
    safe_title = escape(title, quote=True)

    cta_html = ""
    if cta_label and cta_url:
        cta_html = (
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'align="center" style="margin:24px auto">'
            '<tr><td align="center" bgcolor="#5e2b47" '
            'style="background-color:#5e2b47;border-radius:8px;mso-padding-alt:12px 22px">'
            f'<a href="{escape(cta_url, quote=True)}" '
            'style="background-color:#5e2b47;border:1px solid #5e2b47;border-radius:8px;'
            "color:#ffffff;display:inline-block;font-family:Arial,Helvetica,sans-serif;"
            "font-size:15px;font-weight:700;line-height:20px;padding:12px 22px;"
            'text-align:center;text-decoration:none">'
            f"{escape(cta_label, quote=True)}</a>"
            "</td></tr></table>"
        )

    footer_note_html = ""
    if footer_note:
        footer_note_html = (
            '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:12px;'
            'line-height:18px;margin:0 0 10px">'
            f"{escape(footer_note, quote=True)}</p>"
        )

    return (
        "<!doctype html>"
        '<html lang="en">'
        '<head><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width, initial-scale=1.0"></head>'
        '<body style="background-color:#faf7f0;margin:0;padding:0">'
        '<span style="color:#faf7f0;display:none;font-size:1px;line-height:1px;'
        'max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all">'
        f"{preheader}</span>"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="background-color:#faf7f0;border-collapse:collapse;width:100%">'
        '<tr><td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" '
        'style="background-color:#ffffff;border:1px solid #e7e0d4;border-collapse:separate;'
        'border-radius:12px;border-spacing:0;max-width:600px;overflow:hidden;width:100%">'
        '<tr><td style="padding:22px 24px 18px">'
        "<p style=\"color:#5e2b47;font-family:Georgia,'Times New Roman',serif;font-size:22px;"
        'font-weight:700;letter-spacing:-0.3px;line-height:26px;margin:0">Aspirova</p>'
        "</td></tr>"
        '<tr><td bgcolor="#5e2b47" '
        'style="background-color:#5e2b47;font-size:2px;height:2px;line-height:2px">&nbsp;</td></tr>'
        '<tr><td style="padding:28px 24px 4px">'
        "<p style=\"color:#2b2620;font-family:Georgia,'Times New Roman',serif;font-size:22px;"
        'font-weight:700;line-height:30px;margin:0 0 10px">'
        f"{safe_title}</p>"
        f"{intro_html}{body_html}{cta_html}"
        "</td></tr>"
        '<tr><td style="border-top:1px solid #e7e0d4;padding:18px 24px 22px">'
        f"{footer_note_html}"
        '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        "line-height:18px;margin:0 0 8px\">You're receiving this because you use Aspirova. "
        f'<a href="{preference_url}" style="color:#5e2b47;text-decoration:underline">'
        "Manage email preferences</a>.</p>"
        '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        'line-height:18px;margin:0 0 8px">Opportunities are gathered from public sources and '
        "can change — always confirm details on the official page.</p>"
        '<p style="color:#6b6259;font-family:Arial,Helvetica,sans-serif;font-size:12px;'
        'line-height:18px;margin:0">Aspirova — every opportunity, one place.</p>'
        "</td></tr></table></td></tr></table></body></html>"
    )
