import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

LOG_PATH = Path("/Users/danielmoen/carver-v3/.cursor/debug.log")
RUN_ID = os.environ.get("DEBUG_RUN_ID", "pre-fix")


def run(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def repo_slug(remote: str) -> str:
    remote = remote.strip()
    if remote.endswith(".git"):
        remote = remote[:-4]
    if remote.startswith("git@github.com:"):
        return remote.split("git@github.com:", 1)[1]
    if "github.com/" in remote:
        return remote.split("github.com/", 1)[1]
    return remote


def extract_var(output: str, key: str) -> str | None:
    prefix = f"║ {key}"
    for line in output.splitlines():
        if line.startswith(prefix) and "│" in line:
            _, _, value = line.partition("│")
            value = value.replace("║", "").strip()
            if value:
                return value
    return None


def log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    payload = {
        "id": f"log_{int(time.time() * 1000)}_{hypothesis_id}",
        "timestamp": int(time.time() * 1000),
        "runId": RUN_ID,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
    }
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def main() -> None:
    repo_root = Path(__file__).resolve().parent

    git_code, git_out, git_err = run(["git", "remote", "get-url", "origin"])
    local_repo = repo_slug(git_out)
    # region agent log
    log(
        "H2",
        "debug_railway_probe.py:29",
        "git remote origin inspected",
        {
            "exitCode": git_code,
            "origin": local_repo,
            "stderr": git_err.strip(),
        },
    )
    # endregion

    api_paths = {
        "apiDirExists": (repo_root / "api").is_dir(),
        "apiDockerfileExists": (repo_root / "api" / "Dockerfile").is_file(),
        "apiRailwayTomlExists": (repo_root / "api" / "railway.toml").is_file(),
    }
    # region agent log
    log(
        "H1",
        "debug_railway_probe.py:45",
        "local api paths inspected",
        api_paths,
    )
    # endregion

    local_builder = None
    railway_toml = repo_root / "api" / "railway.toml"
    if railway_toml.is_file():
        for line in railway_toml.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("builder"):
                local_builder = line.split("=", 1)[1].strip().strip('"')
                break

    # region agent log
    log(
        "H3",
        "debug_railway_probe.py:63",
        "local api railway builder inspected",
        {"localBuilder": local_builder},
    )
    # endregion

    vars_code, vars_out, vars_err = run(["railway", "variables", "--service", "api"])
    vars_summary = {
        "exitCode": vars_code,
        "stderr": vars_err.strip(),
        "hasAppEnvProduction": "APP_ENV                       │ production" in vars_out,
        "hasSecretKey": "SECRET_KEY" in vars_out,
        "hasAdminPassword": "ADMIN_PASSWORD" in vars_out,
        "adminPasswordStillDefault": "change-this-password" in vars_out,
        "autoLoginEnabled": "AUTO_LOGIN_AS_ADMIN           │ true" in vars_out,
    }
    # region agent log
    log(
        "H1",
        "debug_railway_probe.py:58",
        "railway api production guard variables inspected",
        vars_summary,
    )
    # endregion

    status_code, status_out, status_err = run(["railway", "status", "--json"])
    status_data = {}
    if status_code == 0:
        try:
            status_data = json.loads(status_out)
        except json.JSONDecodeError:
            status_data = {"parseError": True}

    api_service = {}
    for edge in status_data.get("services", {}).get("edges", []):
        node = edge.get("node", {})
        if node.get("name") == "api":
            api_service = node
            break

    latest = (
        api_service.get("serviceInstances", {})
        .get("edges", [{}])[0]
        .get("node", {})
        .get("latestDeployment", {})
    )
    meta = latest.get("meta", {})
    source = (
        api_service.get("serviceInstances", {})
        .get("edges", [{}])[0]
        .get("node", {})
        .get("source", {})
    )

    # region agent log
    log(
        "H2",
        "debug_railway_probe.py:98",
        "railway api service source inspected",
        {
            "exitCode": status_code,
            "stderr": status_err.strip(),
            "sourceRepo": source.get("repo"),
            "localRepo": local_repo,
            "repoMismatch": bool(source.get("repo")) and source.get("repo") != local_repo,
            "deploymentId": latest.get("id"),
            "configErrors": meta.get("configErrors", []),
            "serviceManifestBuilder": meta.get("serviceManifest", {})
            .get("build", {})
            .get("builder"),
        },
    )
    # endregion

    # region agent log
    log(
        "H4",
        "debug_railway_probe.py:117",
        "local api path compared against railway root-directory error",
        {
            "localApiDirExists": api_paths["apiDirExists"],
            "configFile": meta.get("configFile"),
            "rootDirectory": meta.get("rootDirectory"),
            "healthcheckPath": meta.get("serviceManifest", {}).get("deploy", {}).get("healthcheckPath"),
            "railwayConfigErrors": meta.get("configErrors", []),
        },
    )
    # endregion

    public_domain = extract_var(vars_out, "RAILWAY_PUBLIC_DOMAIN") or extract_var(vars_out, "RAILWAY_SERVICE_API_URL")
    health_url = f"https://{public_domain}/health" if public_domain else None
    health_probe = {"url": health_url, "reachable": False}
    if health_url:
        try:
            with urllib.request.urlopen(health_url, timeout=15) as resp:
                body = resp.read(200).decode("utf-8", errors="replace")
                health_probe.update(
                    {
                        "reachable": True,
                        "statusCode": resp.status,
                        "bodySnippet": body[:200],
                    }
                )
        except urllib.error.HTTPError as exc:
            body = exc.read(200).decode("utf-8", errors="replace")
            health_probe.update(
                {
                    "statusCode": exc.code,
                    "bodySnippet": body[:200],
                    "error": str(exc),
                }
            )
        except Exception as exc:
            health_probe["error"] = str(exc)

    # region agent log
    log(
        "H5",
        "debug_railway_probe.py:149",
        "public api health endpoint probed",
        health_probe,
    )
    # endregion


if __name__ == "__main__":
    main()
