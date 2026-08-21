"""Browser-side inactivity and absolute-session controls for ReEDS-Proxy."""

from __future__ import annotations

import os

from bokeh.document import Document


DEFAULT_IDLE_TIMEOUT_SECONDS = 30 * 60
_TRUE_VALUES = {"1", "true", "yes"}


def session_limits_enabled() -> bool:
    """Return whether hosted session enforcement is enabled."""
    return os.environ.get("REEDS_PROXY_ENABLE_SESSION_LIMITS", "false").lower() in _TRUE_VALUES


def _positive_seconds(environment_name: str, default: int) -> int:
    value = int(os.environ.get(environment_name, default))
    if value <= 0:
        raise ValueError(f"{environment_name} must be greater than zero")
    return value


def install_session_limits(document: Document) -> bool:
    """Install hosted session enforcement and report whether it was enabled."""
    if not session_limits_enabled():
        return False

    idle_timeout_milliseconds = 1000 * _positive_seconds(
        "REEDS_PROXY_IDLE_TIMEOUT_SECONDS",
        DEFAULT_IDLE_TIMEOUT_SECONDS,
    )
    document.template = f"""
{{% block postamble %}}
{{{{ super() }}}}
<script>
(() => {{
  "use strict";

  const idleTimeoutMilliseconds = {idle_timeout_milliseconds};
  const checkIntervalMilliseconds = 30000;
  let lastActivityMilliseconds = Date.now();
  let expiresAtMilliseconds = null;
  let signingOut = false;

  const signOut = () => {{
    if (signingOut) return;
    signingOut = true;
    window.location.replace("/logout");
  }};

  const checkSession = () => {{
    const now = Date.now();
    if (now - lastActivityMilliseconds >= idleTimeoutMilliseconds) signOut();
    if (expiresAtMilliseconds !== null && now >= expiresAtMilliseconds) signOut();
  }};

  const recordActivity = () => {{
    lastActivityMilliseconds = Date.now();
  }};

  ["keydown", "pointerdown", "pointermove", "touchstart", "wheel"].forEach((eventName) => {{
    window.addEventListener(eventName, recordActivity, {{ passive: true }});
  }});
  window.addEventListener("focus", checkSession);
  document.addEventListener("visibilitychange", checkSession);
  window.setInterval(checkSession, checkIntervalMilliseconds);

  fetch("/session/status", {{ cache: "no-store", credentials: "same-origin" }})
    .then((response) => {{
      if (!response.ok) throw new Error("Session is no longer authenticated");
      return response.json();
    }})
    .then((status) => {{
      expiresAtMilliseconds = status.expires_at_milliseconds;
      checkSession();
    }})
    .catch(signOut);
}})();
</script>
{{% endblock %}}
"""
    return True
