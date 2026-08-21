# ReEDS-Proxy on Google Cloud

This folder packages the ReEDS-Proxy Stage 2 Bokeh application for Cloud Run. Users open a
URL and enter a shared password. They do not need a Google account, clone the
repository, or download the trained models.

## What is deployed

- The container image contains the Stage 2 dashboard code, inputs, evaluation
  outputs, and the two ReEDS BokehPivot style CSVs.
- A private Cloud Storage bucket contains only:
  - `Stage2/overall/models/*.joblib`
  - `Stage2/regional/models/*.joblib`
- Google Secret Manager contains separate one-way dashboard and admin
  password hashes plus a random cookie signing key. Plain-text passwords are
  not stored in Google Cloud or GitHub.
- `surrogate_ml_data` and the `*_premerge` model directories are not required
  by the dashboard.

## Add shared-password access to the existing prototype

From PowerShell at the repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File `
  postprocessing\reedssurr\Stage2\deploy\gcp\configure-shared-password.ps1 `
  -ProjectId "reeds-agent-api" `
  -ModelBucket "reeds-surrogate-models-reeds-agent-api"
```

The script asks for the password twice using hidden input. It then stores only
the PBKDF2 password hash, builds the authenticated image, deploys it, checks
that Cloud Run is ready, and gives `allUsers` permission to invoke the service.
That public invocation permission is intentional: the application login page
performs authentication. The model bucket itself remains private.

The dashboard will be available at:

```text
https://reeds-proxy-daucp3gr4a-uc.a.run.app/reeds_proxy
```

Add `-KeepPrivate` to `configure-shared-password.ps1` when testing a full
deployment that should not yet be reachable by other people.

If a browser reports `ERR_NAME_NOT_RESOLVED` for the `run.app` address while
the service is Ready, try a phone hotspot or another network. Some corporate
DNS configurations block or override the `run.app` zone. A custom domain is
the durable option when users must access the dashboard from such a network.

Shared passwords are appropriate for this personal prototype, but they do not
identify individual users. Anyone who receives the password can share it. For
a production or sensitive application, use IAP or another per-user login
system instead.

## Admin portal

The admin portal uses a separate password from the dashboard. It provides:

- an online browser for the deployed ReEDS-Proxy source files;
- a ZIP download containing the complete Stage 2 dashboard, training,
  data-processing, and GCP deployment code;
- a ZIP download containing all deployed Stage 2 input data; and
- individually streamed downloads for every `.joblib` artifact in the private
  model bucket, plus one streamed archive containing all trained models.

The bucket remains private. Cloud Run reads each requested model through its
runtime service account and sends it only after admin authentication.

For the initial admin-portal deployment, run this command from the repository
root. The script prompts twice for a new admin password:

```powershell
powershell -ExecutionPolicy Bypass -File `
  postprocessing\reedssurr\Stage2\deploy\gcp\configure-admin-access.ps1 `
  -ProjectId "reeds-agent-api" `
  -ModelBucket "reeds-surrogate-models-reeds-agent-api"
```

The admin portal will be available at:

```text
https://reeds-proxy-daucp3gr4a-uc.a.run.app/admin
```

For later admin-password changes, add `-PasswordOnly`. That creates a new
secret version and Cloud Run revision without rebuilding the container image.

## First deployment in another Google Cloud project

Prerequisites:

1. A Google Cloud project with billing enabled.
2. Permission to create Cloud Run, Cloud Build, Artifact Registry, Cloud
   Storage, Secret Manager, and IAM resources.
3. Google Cloud CLI installed and authenticated with `gcloud auth login`.

From PowerShell at the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File `
  postprocessing\reedssurr\Stage2\deploy\gcp\bootstrap.ps1 `
  -ProjectId "YOUR_PROJECT_ID" `
  -ModelBucket "YOUR_GLOBALLY_UNIQUE_BUCKET_NAME"
```

The script validates the two local production model directories, creates the
private bucket and runtime identity, uploads the models, and then invokes the
shared-password setup. It prompts for the password before deployment.

The prototype scales to zero when idle to avoid continuous 8 GiB instance
charges. The first request after an idle period will be slower while the
container starts and models are loaded. Set the service minimum instances to
one temporarily when preparing a live demonstration.

Hosted dashboard sessions automatically sign out after 30 minutes without
browser activity, and all dashboard and admin sessions expire two hours after
login. The deployment configures these limits with
`REEDS_PROXY_ENABLE_SESSION_LIMITS`, `REEDS_PROXY_IDLE_TIMEOUT_SECONDS`, and
`REEDS_PROXY_MAX_SESSION_SECONDS`. The enable flag is intentionally absent
from the local launcher, where no hosted authentication routes are available.
Closing an expired hosted dashboard session also closes its billable WebSocket.

BokehJS is embedded directly in each application page (`BOKEH_RESOURCES=inline`)
so Cloud Run never exposes container-internal `0.0.0.0:8080` asset URLs to the
browser and does not require a separate JavaScript CDN.

## GitHub automatic deployment

After the first deployment works, connect the GitHub repository in Cloud
Build and create a push trigger using `cloudbuild.yaml` in this directory.
Set these trigger substitutions:

- `_REGION`
- `_SERVICE`
- `_ARTIFACT_REPOSITORY`
- `_MODEL_BUCKET`
- `_RUNTIME_SERVICE_ACCOUNT`
- `_PASSWORD_SECRET` (normally `reedssurr-password-hash`)
- `_ADMIN_PASSWORD_SECRET` (normally `reeds-proxy-admin-password-hash`)
- `_COOKIE_SECRET` (normally `reedssurr-cookie-secret`)

The Cloud Build service account needs permission to build and push images,
deploy Cloud Run revisions, and act as the runtime service account. A GitHub
push then rebuilds and redeploys the code while preserving the existing Cloud
Run access policy. Models and passwords remain outside GitHub.

## Local container test

The hosted configuration intentionally fails closed when the password hash or
admin password hash or cookie signing key is missing. For local testing, set
`REEDSSURR_PASSWORD_HASH` and `REEDSSURR_ADMIN_PASSWORD_HASH` to PBKDF2
hashes, set `BOKEH_COOKIE_SECRET` to a random value, and set
`REEDSSURR_SECURE_COOKIES=false` because localhost does not use HTTPS. Then
build and run the Dockerfile in this directory.
