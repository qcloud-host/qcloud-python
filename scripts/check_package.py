"""Install the built wheel into an isolated consumer, including the realtime extra.

Set QCLOUD_WHEELHOUSE for a fully offline run with previously verified wheels.
This script makes no requests to QCloud or model providers.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import venv
import zipfile

root = Path(__file__).resolve().parent.parent
wheels = sorted((root / "dist").glob("qcloud_ai-*-py3-none-any.whl"))
if len(wheels) != 1:
    raise RuntimeError("Expected one freshly built QCloud wheel")
wheel = wheels[0]
with zipfile.ZipFile(wheel) as archive:
    paths = set(archive.namelist())
    for required in ["qcloud_ai/__init__.py", "qcloud_ai/py.typed", "qcloud_ai/_session_socket.py", "qcloud_ai/resources/queue_runtime.py"]:
        if required not in paths:
            raise RuntimeError(f"Missing wheel file: {required}")
    metadata = next(name for name in paths if name.endswith(".dist-info/METADATA"))
    version = next(line.removeprefix("Version: ") for line in archive.read(metadata).decode().splitlines() if line.startswith("Version: "))

smoke = r'''
import asyncio
from importlib.metadata import version
from importlib.resources import files
import httpx
import qcloud_ai
from qcloud_ai import QCloud, AsyncQCloud, QueueRuntimeQuote, GenerationSocket, AsyncGenerationSocket
from websockets.sync.client import connect as sync_connect
from websockets.asyncio.client import connect as async_connect

assert qcloud_ai.__version__ == version("qcloud-ai") == EXPECTED_VERSION
assert version("websockets") == "15.0.1"
assert files("qcloud_ai").joinpath("py.typed").is_file()
assert callable(sync_connect) and callable(async_connect)
calls = []
def transport(request):
    calls.append(request)
    assert str(request.url) == "https://platform.qcloud.host/api/v1/models"
    assert request.headers["user-agent"] == "qcloud-ai-python/" + EXPECTED_VERSION
    return httpx.Response(200, json={"object": "list", "data": []})
with QCloud(api_key="qc-package-fixture", http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
    assert callable(client.serverless.queue.runtime.endpoints.quote)
    assert callable(client.serverless.queue.runtime.jobs.quote)
    assert callable(client.generation.sessions.open_socket)
    assert client.models.list().data == []
async def run():
    async with AsyncQCloud(api_key="qc-package-fixture", http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))) as client:
        assert callable(client.serverless.queue.runtime.endpoints.quote)
        assert callable(client.serverless.queue.runtime.jobs.quote)
        assert callable(client.generation.sessions.open_socket)
        assert (await client.models.list()).data == []
asyncio.run(run())
assert len(calls) == 2
print("Installed wheel: sync/async imports, realtime dependencies, default API origin and mocked GET passed")
'''
with tempfile.TemporaryDirectory(prefix="qcloud-wheel-") as temporary:
    directory = Path(temporary)
    environment = directory / "venv"
    # POSIX release containers may keep temporary storage noexec. A symlink to
    # the trusted interpreter keeps that protection while making the venv usable.
    venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "QCLOUD_API_KEY", "QCLOUD_BASE_URL", "QCLOUD_ORGANIZATION_ID"}}
    install = [str(python), "-m", "pip", "install", "--disable-pip-version-check"]
    if os.environ.get("QCLOUD_WHEELHOUSE"):
        install += ["--no-index", "--find-links", str(Path(os.environ["QCLOUD_WHEELHOUSE"]).resolve())]
    subprocess.run([*install, str(wheel) + "[realtime]"], cwd=directory, env=env, check=True, timeout=120)
    subprocess.run([str(python), "-m", "pip", "check"], cwd=directory, env=env, check=True, timeout=30)
    (directory / "smoke.py").write_text("EXPECTED_VERSION = " + json.dumps(version) + "\n" + smoke, encoding="utf-8")
    subprocess.run([str(python), "-I", "smoke.py"], cwd=directory, env=env, check=True, timeout=30)
print(json.dumps({"package": "qcloud-ai", "version": version, "wheel": wheel.name}))
