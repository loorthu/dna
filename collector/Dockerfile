# The airgap collector — mirrors a meeting recording through DNA and takes custody of it.
#
# The collection LOGIC is not vendored here: it is copied from the backend's `dna` package (the
# `dna` build context, wired in docker-compose.frontend.yml), so it is the same code the backend
# test suite covers rather than a second copy that drifts. Only the runnable shell — the HTTP
# client and the poll loop — lives in this directory.
# The base image, as an arg so a site can pull it through its own registry mirror rather than
# Docker Hub — which is what an internal build host usually needs, and what the air-gapped one
# already did by other means (SPI_NOTES.md documents the same override as a --build-context).
ARG PYTHON_IMAGE=python:3.11-slim
FROM ${PYTHON_IMAGE}

WORKDIR /app

# Optional internal PyPI mirror, matching backend/Dockerfile so the air-gapped host builds the
# same way. Defaults to public PyPI for a normal build.
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=

COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" \
        ${PIP_TRUSTED_HOST:+--trusted-host $PIP_TRUSTED_HOST} \
        -r requirements.txt

# The shared collection logic. An EMPTY package marker rather than the backend's own __init__,
# which pulls in the whole application's imports; both modules deliberately depend on nothing but
# the standard library, which is what lets them be lifted out like this. recording_posters is the
# thumbnailer — it draws the play badge itself for the same reason, so no image library and no
# GPL-only ffmpeg filter has to be present for a poster frame to come out identical on every host.
COPY --from=dna recording_collector.py /app/dna/recording_collector.py
COPY --from=dna recording_posters.py /app/dna/recording_posters.py
# Only for its path validator — the collector derives the path it reports to DNA from its own
# configured directory, and that path has to be provably under the root nginx serves.
COPY --from=dna recording_archive_path.py /app/dna/recording_archive_path.py
RUN touch /app/dna/__init__.py

COPY main.py .

# Fail fast and visibly if the bundled ffmpeg did not survive the build — discovering it at the
# end of the first real meeting would cost that recording's audio.
RUN python -c "import imageio_ffmpeg, subprocess, sys; \
    exe = imageio_ffmpeg.get_ffmpeg_exe(); \
    out = subprocess.run([exe, '-hide_banner', '-encoders'], capture_output=True, text=True); \
    sys.exit(0 if ' aac ' in out.stdout else 'bundled ffmpeg has no aac encoder')"

# Run as a NON-ROOT user. Archives outlive this container and are the only copy of a meeting once
# the upstream is released, so they must not be left owned by a uid nobody can act as: root-owned
# files cannot be rotated, moved or deleted by whoever owns the share.
#
# The uid is chosen at RUN time (compose passes `user:`), because the only correct value is one
# that can write the real archive mount — that is a property of the deployment, not of this image.
# 1000 is a conventional default for running unprivileged out of the box, not a claim about any
# particular host.
#
# Staging is 1777 (world-writable, sticky) so a named volume created from this image is writable
# whichever uid is chosen. It lives inside a private volume and holds half-mirrored parts, so the
# looser mode costs nothing; requiring the image's uid to match the deployment's would mean
# rebuilding the image per host.
RUN mkdir -p /staging && chmod 1777 /staging \
    && groupadd -g 1000 collector \
    && useradd -u 1000 -g 1000 -M -d /app -s /usr/sbin/nologin collector

ENV PYTHONUNBUFFERED=1
USER 1000:1000
CMD ["python", "main.py"]
