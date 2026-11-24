"""Presentational helpers for the OpenCertif design system (.oc-card,
.oc-badge-*, .oc-dot-*, ...). See docs/design_system.md.

Icons use Streamlit's native Material Symbols shortcode (":material/xxx:"),
supported directly by st.button/st.page_link/st.markdown. Note: the
shortcode is only substituted inside genuine markdown text; it is NOT
substituted inside raw HTML passed via unsafe_allow_html=True (verified
against Streamlit's own frontend: the substitution runs on markdown text
nodes, while raw HTML is handled by a separate rehype-raw pass that never
sees it). So any icon that needs to sit next to raw HTML content is
rendered as its own standalone st.markdown() call instead of being
embedded in an HTML string.
"""

import streamlit as st

_DOT_CLASSES = {
    "success": "oc-dot-success",
    "warning": "oc-dot-warning",
    "error": "oc-dot-error",
}


def page_title(text: str) -> None:
    st.markdown(f'<h1 class="oc-page-title">{text}</h1>', unsafe_allow_html=True)


def card_start(title: str = "") -> None:
    html = '<div class="oc-card">'
    if title:
        html += f'<h3 class="oc-card-title">{title}</h3>'
    st.markdown(html, unsafe_allow_html=True)


def card_end() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def badge(kind: str, text: str) -> str:
    """Returns the HTML for an .oc-badge-{kind} span (success | error | warning).

    Uses a plain colored CSS dot in place of an icon (see .oc-dot in style.css).
    """
    dot_class = _DOT_CLASSES.get(kind, "oc-dot-success")
    return (
        f'<span class="oc-badge oc-badge-{kind}">'
        f'<span class="oc-dot {dot_class}"></span>{text}</span>'
    )


def dot(kind: str) -> str:
    """Returns the HTML for a small status dot (success | warning | error)."""
    css_class = _DOT_CLASSES.get(kind, "oc-dot-success")
    return f'<span class="oc-dot {css_class}"></span>'


def field_row(label: str, value: str) -> str:
    return (
        '<div class="oc-field-row">'
        f'<span class="oc-field-label">{label}</span>'
        f'<span class="oc-field-value">{value}</span>'
        "</div>"
    )


def upload_zone(title: str, subtitle: str, key: str = "oc-upload-zone") -> None:
    """Renders a styled drag-and-drop-looking box (icon + title + subtitle).

    The Material icon must be its own st.markdown() call (see module
    docstring), so the box is an st.container(key=...) styled via CSS
    (.st-key-oc-upload-zone in style.css) rather than a single HTML blob.
    """
    with st.container(key=key):
        st.markdown(":material/upload:")
        st.markdown(
            f'<p class="oc-upload-title">{title}</p>'
            f'<p class="oc-upload-subtitle">{subtitle}</p>',
            unsafe_allow_html=True,
        )
