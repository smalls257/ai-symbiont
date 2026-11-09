"""The one door out: every outbound HTTP call from the published package goes through `post_json`.

It reaches local servers only; research runs reach remote APIs through `remote_send`.

Model files come in through `download_file`, the GET-only second door (Hugging Face only).
"""

from symbiont.egress.client import post_json
from symbiont.egress.download import DownloadError, download_file, file_url, get_json, listing_url
from symbiont.egress.policy import Destination, EgressRefusedError, Endpoint, check_outbound

__all__ = [
    "Destination",
    "DownloadError",
    "EgressRefusedError",
    "Endpoint",
    "check_outbound",
    "download_file",
    "file_url",
    "get_json",
    "listing_url",
    "post_json",
]
