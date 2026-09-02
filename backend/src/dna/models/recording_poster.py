"""One shot's poster frame: a still from the part of the meeting recording that discussed it.

The bytes live here, in DNA, rather than only on the share the collector wrote them to. That is
the one thing about this model worth explaining, because DNA deliberately keeps no copy of the
recording itself: the notes email is composed on this side of the airgap and embeds the thumbnail
in the message, and it has to, because a mail client fetching an image from the share only works
for a reader inside the network — Gmail's web client asks a Google proxy to fetch it, and that
proxy cannot reach an internal host. A few tens of kB per shot is a different proposition from
several hundred MB of video, and it is what makes the picture arrive.

`filename` is the copy on the share, kept so the two can be told apart from either side.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RecordingPoster(BaseModel):
    """A stored poster frame, keyed by playlist and version."""

    playlist_id: int
    version_id: int
    image: bytes = Field(description="The JPEG itself, as stored")
    content_type: str = "image/jpeg"
    filename: Optional[str] = Field(
        default=None,
        description="What the collector called the copy it left on the share, which nginx "
        "serves under /recordings/. Recorded so a poster in the database can be matched to the "
        "file beside the archive it came from.",
    )
    recording_id: Optional[int] = Field(
        default=None,
        description="The recording the frame was taken from. A playlist that hosts a second "
        "meeting replaces its posters, and this says which meeting the current ones are of.",
    )
    updated_at: Optional[datetime] = None
