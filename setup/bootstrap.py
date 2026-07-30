"""One-command bootstrap: from "Docker + uv installed" to a demo-ready Lore environment.

Collapses README.md Quickstart steps 1-5 (DataHub quickstart, demo Postgres, seed,
ingest, register the learnings structured property) into one idempotent run. Each
step prints a [n/6] line and is SKIPPED with a note if already satisfied. Finishes
by running setup/doctor.py, passing through its verdict as this script's result.

Prerequisites: Docker Desktop (or another docker daemon), uv (https://docs.astral.sh/uv/).
Example: uv run python setup/bootstrap.py
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psycopg2

REPO_ROOT = Path(__file__).resolve().parent.parent
import doctor  # setup/doctor.py, same directory: reuse its checks, don't re-implement them

GMS_URL = "http://localhost:8080"
UI_URL = "http://localhost:9002"
TOTAL_STEPS = 6

def header(n, title): print(f"[{n}/{TOTAL_STEPS}] {title}")
def ok(msg): print(f"    OK: {msg}")
def skip(msg): print(f"    SKIP: {msg}")
def fail(msg, fix):
    print(f"    FAIL: {msg}\n    Fix: {fix}")
    sys.exit(1)

def resolve_uvx() -> str:
    """uvx isn't always on PATH even when uv is; fall back to the uvx next to uv."""
    found = shutil.which("uvx")
    if found:
        return found
    uv_path = shutil.which("uv")
    if uv_path:
        candidate = Path(uv_path).with_name("uvx.exe" if os.name == "nt" else "uvx")
        if candidate.exists():
            return str(candidate)
    return "uvx"

def wait_for(check_fn, timeout_s, interval_s):
    start = time.time()
    while time.time() - start < timeout_s:
        passed, detail = check_fn()
        if passed:
            return True, detail
        time.sleep(interval_s)
    return False, "timed out waiting for it to become ready"

def step1_prerequisites():
    header(1, "Checking prerequisites (docker, uv, uvx)")
    docker_path = shutil.which("docker")
    if not docker_path:
        fail("docker not found on PATH.", "install Docker Desktop, then retry.")
    try:
        result = subprocess.run([docker_path, "info"], capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        fail("`docker info` timed out.", "start Docker Desktop, wait until it reports running, then retry.")
    if result.returncode != 0:
        fail(f"Docker daemon not reachable ({result.stderr.strip()[-200:]}).",
             "start Docker Desktop (or your docker daemon) and retry.")
    if not shutil.which("uv"):
        fail("uv not found on PATH.", "install uv (https://docs.astral.sh/uv/) and retry.")
    uvx_path = resolve_uvx()
    if uvx_path == "uvx" and not shutil.which("uvx"):
        fail("uvx not found on PATH or next to uv.", "install uv (https://docs.astral.sh/uv/); it bundles uvx.")
    ok(f"docker reachable, uv and uvx present ({uvx_path})")
    return docker_path, uvx_path

def step2_datahub_quickstart(uvx_path):
    header(2, "DataHub quickstart (GMS + UI)")
    gms_ok, _ = doctor.http_ok(f"{GMS_URL}/health")
    if gms_ok:
        skip(f"DataHub GMS already healthy at {GMS_URL}/health")
        return
    print("    Long step: a cold start pulls Docker images, ~7-10 min. Later runs skip this.")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [uvx_path, "--from", "acryl-datahub", "datahub", "docker", "quickstart"]
    try:
        subprocess.run(cmd, env=env, timeout=900)
    except subprocess.TimeoutExpired:
        print("    NOTE: quickstart command exceeded 900s; checking health directly anyway.")
    except OSError as exc:
        fail(f"could not launch quickstart ({exc}).",
             "run `PYTHONIOENCODING=utf-8 datahub docker quickstart` manually (README Quickstart step 1).")
    # Known cosmetic exit-1 UnicodeEncodeError on Windows even on full success: judge
    # success by health endpoints, bounded to ~10 min, never by the command's exit code.
    def both_healthy():
        gms_ok, gms_detail = doctor.http_ok(f"{GMS_URL}/health")
        return doctor.http_ok(UI_URL) if gms_ok else (False, gms_detail)
    passed, detail = wait_for(both_healthy, timeout_s=600, interval_s=10)
    if not passed:
        fail(f"DataHub GMS/UI did not become healthy in time ({detail}).",
             "check `docker ps` and setup/NOTES-datahub-quickstart.md, then retry "
             "`PYTHONIOENCODING=utf-8 datahub docker quickstart` (README Quickstart step 1).")
    ok("DataHub GMS and UI healthy")

def postgres_reachable() -> bool:
    try:
        conn = psycopg2.connect(doctor.DATABASE_URL, connect_timeout=3)
    except psycopg2.OperationalError:
        return False
    conn.close()
    return True

def step3_demo_postgres(docker_path):
    header(3, "Demo Postgres (docker compose)")
    if postgres_reachable():
        skip(f"demo Postgres already reachable at {doctor.DATABASE_URL}")
        return
    compose_file = REPO_ROOT / "demo" / "docker-compose.yml"
    result = subprocess.run([docker_path, "compose", "-f", str(compose_file), "up", "-d"],
                             cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"docker compose up failed: {result.stderr.strip()[-300:]}",
             "run `docker compose -f demo/docker-compose.yml up -d` manually (README Quickstart step 2).")
    passed, _ = wait_for(lambda: (postgres_reachable(), "waiting"), timeout_s=60, interval_s=3)
    if not passed:
        fail("demo Postgres did not become reachable within 60s.",
             "check `docker ps` for dhmem-demo-postgres (README Quickstart step 2).")
    ok(f"demo Postgres reachable at {doctor.DATABASE_URL}")

def step4_seed():
    header(4, "Seed the demo warehouse")
    seeded, detail = doctor.check_postgres()
    if seeded:
        skip(detail)
        return
    result = subprocess.run([sys.executable, str(REPO_ROOT / "setup" / "seed_warehouse.py")], cwd=REPO_ROOT)
    if result.returncode != 0:
        fail("setup/seed_warehouse.py exited non-zero.",
             "run `uv run python setup/seed_warehouse.py` manually (README Quickstart step 3).")
    seeded, detail = doctor.check_postgres()
    if not seeded:
        fail(f"warehouse still not seeded after running the seed script ({detail}).",
             "run `uv run python setup/seed_warehouse.py` manually (README Quickstart step 3).")
    ok(detail)

def step5_ingest(uvx_path):
    header(5, "Ingest demo warehouse into DataHub")
    datasets_ok, _ = doctor.check_datasets_exist(GMS_URL)
    lineage_ok, _ = doctor.check_lineage(GMS_URL)
    if datasets_ok and lineage_ok:
        skip("all 4 datasets and the lineage edge already present in DataHub")
        return
    recipe = REPO_ROOT / "setup" / "ingest_postgres.yml"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [uvx_path, "--from", "acryl-datahub[postgres]==1.6.0.16", "datahub", "ingest", "-c", str(recipe)]
    result = None
    try:
        result = subprocess.run(cmd, env=env, cwd=REPO_ROOT, timeout=300, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        print("    NOTE: ingest command exceeded 300s; checking DataHub directly anyway.")
    # Judged by GraphQL (setup/doctor.py checks), not exit code: a non-zero exit
    # doesn't always mean nothing landed, a zero exit doesn't guarantee lineage.
    datasets_ok, datasets_detail = doctor.check_datasets_exist(GMS_URL)
    if not datasets_ok:
        tail = result.stderr.strip()[-300:] if result else ""
        fail(f"{datasets_detail} {tail}".strip(),
             'run `PYTHONIOENCODING=utf-8 uvx --from "acryl-datahub[postgres]==1.6.0.16" datahub ingest '
             "-c setup/ingest_postgres.yml` manually (README Quickstart step 4).")
    lineage_ok, lineage_detail = doctor.check_lineage(GMS_URL)
    if not lineage_ok:
        fail(lineage_detail,
             "re-run the ingest command above; see setup/NOTES-datahub-quickstart.md, section Ingestion.")
    ok(f"{datasets_detail}; {lineage_detail}")

def step6_register_property():
    header(6, "Register the learnings structured property")
    registered, detail = doctor.check_structured_property(GMS_URL)
    if registered:
        skip(detail)
        return
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "setup" / "register_properties.py")], cwd=REPO_ROOT
    )
    if result.returncode != 0:
        fail("setup/register_properties.py exited non-zero.",
             "run `uv run python setup/register_properties.py` manually (README Quickstart step 5).")
    registered, detail = doctor.check_structured_property(GMS_URL)
    if not registered:
        fail(f"property still not registered after running the script ({detail}).",
             "run `uv run python setup/register_properties.py` manually (README Quickstart step 5).")
    ok(detail)

def main() -> int:
    print("Lore bootstrap: setting up the demo environment.\n")
    docker_path, uvx_path = step1_prerequisites()
    step2_datahub_quickstart(uvx_path)
    step3_demo_postgres(docker_path)
    step4_seed()
    step5_ingest(uvx_path)
    step6_register_property()
    print("\nAll setup steps complete. Running the doctor for the final verdict:\n")
    return doctor.main()

if __name__ == "__main__":
    raise SystemExit(main())
