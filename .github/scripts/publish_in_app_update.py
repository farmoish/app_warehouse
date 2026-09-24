"""Point the Farmoish POS in-app updater at a published APK.

Updates the Remote Config keys the app reads (AppReleaseRemoteDataSource in
farmoish-pos-app). `android_force_update` (forced vs optional) is only created
as `false`; after that it is set by hand in the Firebase console.
An APK older than the published one is rejected: devices cannot downgrade.

Env: FIREBASE_SERVICE_ACCOUNT_JSON, FIREBASE_PROJECT_ID, VERSION_NAME,
VERSION_CODE, APK_URL (public download URL of the APK).
"""

import json
import os
import sys

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/firebase.remoteconfig"]
TIMEOUT = 60


def env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is not set")
    return value


def ok(resp):
    if resp.status_code >= 300:
        sys.exit(
            f"{resp.request.method} {resp.url.split('?')[0]} -> "
            f"HTTP {resp.status_code}: {resp.text[:500]}"
        )
    return resp


def find_parameter(template, key):
    if key in template.get("parameters", {}):
        return template["parameters"][key]
    for group in template.get("parameterGroups", {}).values():
        if key in group.get("parameters", {}):
            return group["parameters"][key]
    return None


def set_parameter(template, key, value_type, value):
    param = find_parameter(template, key)
    if param is None:
        param = template.setdefault("parameters", {})[key] = {"valueType": value_type}
    param["defaultValue"] = {"value": value}


def published_version_code(template):
    param = find_parameter(template, "android_latest_version_code") or {}
    value = param.get("defaultValue", {}).get("value", "0")
    return int(value) if value.isdigit() else 0


def publish_remote_config(session, project_id, version_name, version_code, apk_url):
    url = f"https://firebaseremoteconfig.googleapis.com/v1/projects/{project_id}/remoteConfig"
    current = ok(session.get(url, timeout=TIMEOUT))
    template = current.json()

    published = published_version_code(template)
    if int(version_code) < published:
        sys.exit(
            f"versionCode {version_code} is older than the published {published}. "
            f"Build with --build-number greater than {published}."
        )

    set_parameter(template, "android_latest_version_code", "NUMBER", version_code)
    set_parameter(template, "android_latest_version_name", "STRING", version_name)
    set_parameter(template, "android_apk_url", "STRING", apk_url)
    if find_parameter(template, "android_force_update") is None:
        set_parameter(template, "android_force_update", "BOOLEAN", "false")

    body = {
        key: template[key]
        for key in ("conditions", "parameters", "parameterGroups")
        if key in template
    }
    body["version"] = {"description": f"Release {version_name}+{version_code}"}
    ok(
        session.put(
            url,
            json=body,
            headers={"If-Match": current.headers["ETag"]},
            timeout=TIMEOUT,
        )
    )


def main():
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(env("FIREBASE_SERVICE_ACCOUNT_JSON")), scopes=SCOPES
    )
    session = AuthorizedSession(credentials)
    version_name = env("VERSION_NAME")
    version_code = env("VERSION_CODE")
    apk_url = env("APK_URL")

    publish_remote_config(
        session, env("FIREBASE_PROJECT_ID"), version_name, version_code, apk_url
    )
    print(f"Remote Config now points at {version_name}+{version_code}: {apk_url}")


if __name__ == "__main__":
    main()
