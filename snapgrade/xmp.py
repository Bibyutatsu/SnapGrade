"""Write XMP sidecars compatible with Lightroom / Bridge / darktable.

We hand-write the XML rather than pulling in python-xmp-toolkit (which wraps
Exempi, a heavy C dep). The XMP we emit is intentionally minimal: rating,
color label, and our custom reasons array under a private namespace.
"""

from __future__ import annotations

from pathlib import Path

_TEMPLATE = """<?xpacket begin='﻿' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:snapgrade="https://github.com/local/snapgrade/ns/1.0/">
   <xmp:Rating>{rating}</xmp:Rating>
   <xmp:Label>{label}</xmp:Label>
   <snapgrade:Verdict>{verdict}</snapgrade:Verdict>
   <snapgrade:Reasons>
    <rdf:Seq>
{reasons}
    </rdf:Seq>
   </snapgrade:Reasons>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>
"""

_LABEL_MAP = {
    "green": "Green",
    "yellow": "Yellow",
    "red": "Red",
    "blue": "Blue",
    "purple": "Purple",
}


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def sidecar_path_for(image_path: Path) -> Path:
    # Lightroom convention: keep the extension and append .xmp (e.g. IMG_001.NEF.xmp)
    # rather than replacing it, so the sidecar pairs unambiguously with the source.
    return image_path.with_suffix(image_path.suffix + ".xmp")


def write_sidecar(
    image_path: Path,
    rating: int,
    label: str | None,
    verdict: str,
    reasons: list[str],
) -> Path:
    rating = max(0, min(5, int(rating)))
    label_name = _LABEL_MAP.get((label or "").lower(), "")
    reasons_xml = "\n".join(
        f"     <rdf:li>{_xml_escape(r)}</rdf:li>" for r in reasons
    )
    body = _TEMPLATE.format(
        rating=rating,
        label=_xml_escape(label_name),
        verdict=_xml_escape(verdict),
        reasons=reasons_xml,
    )
    out = sidecar_path_for(image_path)
    out.write_text(body, encoding="utf-8")
    return out
