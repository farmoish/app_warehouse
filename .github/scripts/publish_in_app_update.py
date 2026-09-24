"""Publish the newest APK set in APK_DIR as the Farmoish POS in-app update.

APK_DIR holds split APKs (`flutter build apk --split-per-abi`), one per ABI.
The newest version there is verified (package, release signing key) and
published to Firebase Remote Config, which the app reads
(AppReleaseRemoteDataSource in farmoish-pos-app):
  android_latest_version_code  plain versionCode (split APKs carry abi*1000+code)
  android_latest_version_name
  android_apk_urls             {"arm64-v8a": url, ...}, pinned to this commit
  android_force_update         only created as `false`; set in the Firebase console
An older version than the published one is rejected: devices cannot downgrade.

Env: FIREBASE_SERVICE_ACCOUNT_JSON, FIREBASE_PROJECT_ID, APP_PACKAGE,
RELEASE_CERT_SHA256, APK_DIR, ANDROID_HOME, GITHUB_REPOSITORY, GITHUB_SHA.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/firebase.remoteconfig"]
TIMEOUT = 60
# Flutter's --split-per-abi versionCode: abi * 1000 + versionCode.
ABI_VERSION_FACTOR = 1000


def env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is not set")
    return value


def build_tool(name):
    build_tools = Path(env("ANDROID_HOME")) / "build-tools"
    versions = sorted(
        (d for d in build_tools.iterdir() if d.is_dir()),
        key=lambda d: [int(p) if p.isdigit() else 0 for p in re.split(r"[.-]", d.name)],
    )
    return str(versions[-1] / name)


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def inspect_apk(path):
    badging = run(build_tool("aapt2"), "dump", "badging", str(path))
    package = re.search(
        r"^package: name='([^']*)' versionCode='(\d+)' versionName='([^']*)'",
        badging,
        re.M,
    )
    if package is None:
        sys.exit(f"{path}: cannot read package info")
    native = re.search(r"^native-code: (.*)$", badging, re.M)
    abis = re.findall(r"'([^']+)'", native.group(1)) if native else []
    return {
        "path": path,
        "package": package.group(1),
        "version_code": int(package.group(2)),
        "version_name": package.group(3),
        "abis": abis,
    }


def signing_cert(path):
    certs = run(build_tool("apksigner"), "verify", "--print-certs", str(path))
    match = re.search(r"certificate SHA-256 digest: ([0-9a-f]+)", certs)
    return match.group(1) if match else None


def latest_release():
    apks = sorted(Path(env("APK_DIR")).rglob("*.apk"))
    if not apks:
        sys.exit(f"No APKs in {env('APK_DIR')}/")

    infos = [inspect_apk(apk) for apk in apks]
    version_code = max(info["version_code"] % ABI_VERSION_FACTOR for info in infos)
    latest = [
        info
        for info in infos
        if info["version_code"] % ABI_VERSION_FACTOR == version_code
    ]

    app_package = env("APP_PACKAGE")
    release_cert = env("RELEASE_CERT_SHA256")
    urls = {}
    for info in latest:
        path = info["path"]
        if info["package"] != app_package:
            sys.exit(f"{path}: package is {info['package']}, expected {app_package}")
        if signing_cert(path) != release_cert:
            sys.exit(f"{path}: not signed with the release key (android/key.properties)")
        if len(info["abis"]) != 1:
            sys.exit(f"{path}: expected a split APK for one ABI, got {info['abis'] or 'none'}")
        abi = info["abis"][0]
        if abi in urls:
            sys.exit(f"{path}: two APKs for {abi} in version {version_code}")
        urls[abi] = (
            f"https://raw.githubusercontent.com/{env('GITHUB_REPOSITORY')}/"
            f"{env('GITHUB_SHA')}/{quote(path.as_posix())}"
        )

    version_names = {info["version_name"] for info in latest}
    if len(version_names) != 1:
        sys.exit(f"versionCode {version_code} has different versionNames: {version_names}")
    return version_code, version_names.pop(), urls


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


def publish_remote_config(session, project_id, version_code, version_name, urls):
    url = f"https://firebaseremoteconfig.googleapis.com/v1/projects/{project_id}/remoteConfig"
    current = ok(session.get(url, timeout=TIMEOUT))
    template = current.json()

    published = published_version_code(template)
    if version_code < published:
        sys.exit(
            f"versionCode {version_code} is older than the published {published}. "
            f"Raise the +build number in pubspec.yaml above {published}."
        )

    set_parameter(template, "android_latest_version_code", "NUMBER", str(version_code))
    set_parameter(template, "android_latest_version_name", "STRING", version_name)
    set_parameter(template, "android_apk_urls", "JSON", json.dumps(urls, sort_keys=True))
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
    version_code, version_name, urls = latest_release()
    print(f"Latest: {version_name}+{version_code}")
    for abi, url in sorted(urls.items()):
        print(f"  {abi}: {url}")

    credentials = service_account.Credentials.from_service_account_info(
        json.loads(env("FIREBASE_SERVICE_ACCOUNT_JSON")), scopes=SCOPES
    )
    session = AuthorizedSession(credentials)
    publish_remote_config(
        session, env("FIREBASE_PROJECT_ID"), version_code, version_name, urls
    )
    print("Remote Config updated; apps will offer the update.")


if __name__ == "__main__":
    main()
