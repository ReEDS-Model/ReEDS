FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    REEDSSURR_MODELS_DIR=/models

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY postprocessing/reedssurr/Stage2/deploy/gcp/requirements.txt /tmp/requirements.txt
# The current artifacts were trained with sklearn 1.2.2. NGBoost 0.5.8 works
# in that environment, although its newer package metadata now asks pip for
# sklearn >=1.6. Preserve the artifact-compatible environment.
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -m pip install --no-cache-dir --no-deps ngboost==0.5.8

COPY postprocessing/reedssurr/Stage2/code /app/postprocessing/reedssurr/Stage2/code
COPY postprocessing/reedssurr/Stage2/data_processing /app/postprocessing/reedssurr/Stage2/data_processing
COPY postprocessing/reedssurr/Stage2/inputs /app/postprocessing/reedssurr/Stage2/inputs
COPY postprocessing/reedssurr/Stage2/deploy/gcp /app/postprocessing/reedssurr/Stage2/deploy/gcp
COPY postprocessing/reedssurr/Stage2/outputs/overall /app/postprocessing/reedssurr/Stage2/outputs/overall
COPY postprocessing/reedssurr/Stage2/outputs/regional /app/postprocessing/reedssurr/Stage2/outputs/regional
COPY postprocessing/bokehpivot/in/reeds2/tech_map.csv /app/postprocessing/bokehpivot/in/reeds2/tech_map.csv
COPY postprocessing/bokehpivot/in/reeds2/tech_style.csv /app/postprocessing/bokehpivot/in/reeds2/tech_style.csv
RUN python /app/postprocessing/reedssurr/Stage2/deploy/gcp/build_admin_archives.py

COPY postprocessing/reedssurr/Stage2/deploy/gcp/entrypoint.sh /usr/local/bin/reedssurr-entrypoint

RUN chmod +x /usr/local/bin/reedssurr-entrypoint \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/reedssurr-entrypoint"]
