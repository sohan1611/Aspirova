"""The single, inline-styled shell for Aspirova multipart emails."""

from html import escape
from html.parser import HTMLParser
from typing import Literal

from core.config import get_settings
from core.email_components import (
    BODY_FONT,
    BORDER,
    BRAND,
    HEADING_FONT,
    INK,
    MUTED,
    PAGE_BG,
    TABLE,
    _http_url,
    button,
    greeting as email_greeting,
    status_panel,
)

# Only responsive overrides belong here. The complete base design is inline.
RESPONSIVE_CSS = """
@media only screen and (max-width:620px){
.em-outer{padding:0!important}.em-pad{padding-left:16px!important;padding-right:16px!important}
table.em-button,td.em-button{width:100%!important}
a.em-button{display:block!important;box-sizing:border-box!important}
.em-kind{display:none!important}
}
@media (prefers-color-scheme:dark){
.em-page{background-color:#0b1220!important}.em-card{background-color:#111a2e!important}
.em-ink{color:#e8eef8!important}.em-muted{color:#acb9ce!important}
.em-card{border-color:#2c3b53!important}.em-link{color:#9cbcff!important}
}
[data-ogsc] .em-page{background-color:#0b1220!important}
[data-ogsc] .em-card{background-color:#111a2e!important;border-color:#2c3b53!important}
[data-ogsc] .em-ink{color:#e8eef8!important}
[data-ogsc] .em-muted{color:#acb9ce!important}
[data-ogsc] .em-link{color:#9cbcff!important}
"""


class _IntroTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _preheader_text(intro_html: str) -> str:
    parser = _IntroTextParser()
    parser.feed(intro_html)
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def _site_url() -> str:
    return (_http_url(get_settings().site_url) or "https://www.aspirova.org").rstrip("/")


def text_footer(
    unsubscribe_url: str | None = None,
    *,
    variant: Literal["notification", "transactional"] = "notification",
) -> str:
    extra = [f"Unsubscribe from these emails: {url}"] if (url := _http_url(unsubscribe_url)) else []
    receiving = (
        "This is a service email about your Aspirova account."
        if variant == "transactional"
        else "You're receiving this because you have an Aspirova account."
    )
    disclaimer = (
        []
        if variant == "transactional"
        else [
            "Opportunities are gathered from public sources and can change — "
            "always confirm details on the official page."
        ]
    )
    return "\n".join(
        [
            f"Manage email preferences: {_site_url()}/account?section=notifications",
            *extra,
            receiving,
            *disclaimer,
            f"Aspirova · Every opportunity. One place. · aspirova.org ({_site_url()})",
        ]
    )


def email_layout(
    *,
    title: str,
    intro_html: str = "",
    body_html: str,
    cta_label: str | None = None,
    cta_url: str | None = None,
    footer_note: str | None = None,
    unsubscribe_url: str | None = None,
    preheader: str | None = None,
    kind_label: str | None = None,
    greeting: str | None = None,
    summary: str | None = None,
    variant: Literal["notification", "transactional"] = "notification",
    cta_note: str | None = None,
    receiving_note: str | None = None,
    site_url: str | None = None,
    show_preferences: bool = True,
) -> str:
    """Content HTML is trusted and escaped by renderers. Text kwargs are escaped here.

    site_url and receiving_note support the static Supabase dashboard handover.
    """
    site = _http_url(site_url or _site_url()) or "https://www.aspirova.org"
    site = site.rstrip("/")
    safe_site = escape(site, quote=True)
    preference_url = escape(f"{site}/account?section=notifications", quote=True)
    preview = preheader if preheader is not None else _preheader_text(intro_html)
    preview = escape(preview, quote=True) + "&#847;&zwnj;&nbsp;" * 40
    kind = (
        '<td class="em-kind" align="right" style="color:#dbe6ff;font-size:12px">'
        f"{escape(kind_label, quote=True)}</td>"
        if kind_label
        else ""
    )
    hero = ""
    if greeting:
        hero += (
            f'<p class="em-ink" style="color:{INK};font-size:15px;line-height:23px;margin:0 0 8px">'
            f"{escape(greeting, quote=True)}</p>"
        )
    if summary:
        hero += (
            f'<p class="em-ink" style="color:{INK};font-size:16px;font-weight:700;'
            f'line-height:24px;margin:0 0 16px">{escape(summary, quote=True)}</p>'
        )
    cta = ""
    if cta_label and _http_url(cta_url):
        cta = (
            f'<table {TABLE} width="100%"><tr><td align="center" style="padding:24px 0 0">'
            f"{button(cta_label, cta_url)}</td></tr></table>"
        )
        if cta_note:
            cta += (
                f'<p class="em-muted" style="color:{MUTED};font-size:12px;text-align:center">'
                f"{escape(cta_note, quote=True)}</p>"
            )
    footer_link = f"color:{MUTED};text-decoration:underline"
    unsubscribe = ""
    if url := _http_url(unsubscribe_url):
        unsubscribe = (
            f' · <a class="em-muted" href="{escape(url, quote=True)}" '
            f'style="{footer_link}">Unsubscribe</a>'
        )
    receiving = receiving_note or (
        "This is a service email about your Aspirova account."
        if variant == "transactional"
        else "You're receiving this because you have an Aspirova account."
    )
    # Auth emails (Supabase handover) have no preference to manage, and service
    # emails carry no opportunity data, so neither gets those lines.
    footer_lines = (
        [
            f'<a class="em-muted" href="{preference_url}" style="{footer_link}">'
            f"Manage email preferences</a>{unsubscribe}"
        ]
        if show_preferences
        else []
    )
    if footer_note:
        footer_lines.append(escape(footer_note, quote=True))
    footer_lines.append(escape(receiving, quote=True))
    if variant != "transactional":
        footer_lines.append(
            "Opportunities are gathered from public sources and can change — "
            "always confirm details on the official page."
        )
    footer_lines.append(
        "Aspirova · Every opportunity. One place. · "
        f'<a class="em-muted" href="{safe_site}" style="{footer_link}">aspirova.org</a>'
    )
    footer = "".join(f'<p style="margin:0 0 8px">{line}</p>' for line in footer_lines)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="supported-color-schemes" content="light dark">'
        f"<title>{escape(title, quote=True)}</title><style>{RESPONSIVE_CSS}</style>"
        "<!--[if mso]><style>*{font-family:Arial,Helvetica,sans-serif !important}"
        "</style><![endif]--></head>"
        f'<body class="em-page" style="margin:0;padding:0;background-color:{PAGE_BG};{BODY_FONT}">'
        '<span style="display:none;max-height:0;max-width:0;overflow:hidden;mso-hide:all;'
        f'opacity:0;font-size:1px;line-height:1px">{preview}</span>'
        f'<table {TABLE} width="100%" class="em-page" bgcolor="{PAGE_BG}" '
        f'style="background-color:{PAGE_BG};width:100%"><tr>'
        '<td class="em-outer" align="center" style="padding:24px 12px">'
        '<!--[if mso]><table role="presentation" width="600" align="center"><tr><td><![endif]-->'
        f'<table {TABLE} width="600" style="width:100%;max-width:600px">'
        f'<tr><td bgcolor="{BRAND}" class="em-pad" style="background-color:{BRAND};'
        'padding:16px 24px;border-radius:12px 12px 0 0">'
        f'<table {TABLE} width="100%"><tr><td width="32">'
        f'<a href="{safe_site}"><img src="{safe_site}/logo.png" width="32" height="32" '
        'alt="Aspirova" style="border-radius:50%;display:block;border:0"></a></td>'
        f'<td style="padding-left:10px"><a href="{safe_site}" style="color:#ffffff;'
        f'{HEADING_FONT}font-size:20px;font-weight:700;text-decoration:none">Aspirova</a></td>'
        f'{kind}</tr></table></td></tr><tr><td class="em-card em-pad" bgcolor="#ffffff" '
        f'style="background-color:#ffffff;padding:24px;border-bottom:1px solid {BORDER};'
        'border-radius:0 0 12px 12px">'
        f'<h1 class="em-ink" style="color:{INK};{HEADING_FONT}font-size:22px;'
        f'line-height:30px;margin:0 0 16px">{escape(title, quote=True)}</h1>'
        f"{hero}{intro_html}{body_html}{cta}</td></tr><tr>"
        f'<td class="em-muted em-page" align="center" style="color:{MUTED};'
        f'background-color:{PAGE_BG};font-size:12px;line-height:18px;padding:20px 24px 32px">'
        f"{footer}</td></tr></table><!--[if mso]></td></tr></table><![endif]-->"
        "</td></tr></table></body></html>"
    )


def subscription_layout(*, plan_name: str, active: bool, display_name: str | None = None) -> str:
    """Pure account rendering shared by the payment handler and offline previews."""
    site = _site_url()
    title = "Your Aspirova Pro is active" if active else "We couldn't process your payment"
    lines = (
        [f"Your {plan_name} plan is now active.", "Your Pro features are ready whenever you are."]
        if active
        else [
            f"We couldn't process the payment for your {plan_name} plan.",
            "Please update your payment method. Pro features are paused until your payment "
            "succeeds.",
        ]
    )
    return email_layout(
        title=title,
        kind_label="Account",
        variant="transactional",
        greeting=email_greeting(display_name),
        preheader=lines[0],
        body_html=status_panel("success" if active else "urgent", lines),
        cta_label="Open Aspirova" if active else "View your subscription",
        cta_url=site if active else f"{site}/account?section=subscription",
    )
