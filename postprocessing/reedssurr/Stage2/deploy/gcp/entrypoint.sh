#!/bin/sh
set -eu

: "${PORT:=8080}"
: "${REEDSSURR_MODELS_DIR:=/models}"
: "${BOKEH_ALLOW_WS_ORIGIN:=localhost:${PORT}}"
: "${BOKEH_RESOURCES:=inline}"
: "${REEDSSURR_PASSWORD_HASH:?REEDSSURR_PASSWORD_HASH is required}"
: "${REEDSSURR_ADMIN_PASSWORD_HASH:?REEDSSURR_ADMIN_PASSWORD_HASH is required}"
: "${BOKEH_COOKIE_SECRET:?BOKEH_COOKIE_SECRET is required}"

# PowerShell pipes add a trailing newline when creating a Secret Manager
# version. Remove it before Bokeh uses the value to sign login cookies.
BOKEH_COOKIE_SECRET="$(printf '%s' "${BOKEH_COOKIE_SECRET}")"

# Inline BokehJS avoids generating browser URLs that point at the container's
# internal 0.0.0.0:8080 listener when Cloud Run terminates HTTPS upstream.
export REEDSSURR_MODELS_DIR REEDSSURR_ADMIN_PASSWORD_HASH BOKEH_COOKIE_SECRET BOKEH_RESOURCES

exec python /app/postprocessing/reedssurr/Stage2/code/cloud_server.py
