# The airgap collector — mirrors a meeting recording through DNA and takes custody of it.
#
# The collection LOGIC is not vendored here: it is copied from the backend's `dna` package (the
# `dna` build context, wired in docker-compose.frontend.yml), so it is the same code the backend
# test suite covers rather than a second copy that drifts. Only the runnable shell — the HTTP
# client and the poll loop — lives in this directory.
FROM python:3.11-slim

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
# which pulls in the whole application's imports; recording_collector deliberately depends on
# nothing but the standard library, which is what lets it be lifted out like this.
COPY --from=dna recording_collector.py /app/dna/recording_collector.py
RUN touch /app/dna/__init__.py

COPY main.py .

# Fail fast and visibly if the bundled ffmpeg did not survive the build — discovering it at the
# end of the first real meeting would cost that recording's audio.
RUN python -c "import imageio_ffmpeg, subprocess, sys; \
    exe = imageio_ffmpeg.get_ffmpeg_exe(); \
    out = subprocess.run([exe, '-hide_banner', '-encoders'], capture_output=True, text=True); \
    sys.exit(0 if ' aac ' in out.stdout else 'bundled ffmpeg has no aac encoder')"

ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
