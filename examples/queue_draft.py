"""Create a planning record only; no model or worker is launched."""
from uuid import uuid4

from qcloud_ai import QCloud

with QCloud() as client:  # QCLOUD_API_KEY; optional QCLOUD_ORGANIZATION_ID
    catalog = client.serverless.queue.catalog()
    if not catalog.creation_available:
        raise RuntimeError("No queue draft profiles are available")
    # Persist this UUID with the intent before sending. Reuse it only with the
    # same name, profile and organization to recover a lost response explicitly.
    request_id = str(uuid4())
    draft = client.serverless.queue.deployments.create(
        name="My model draft", profile_id=catalog.profiles[0].id,
        client_request_id=request_id,
    )
    print(client.serverless.queue.deployments.retrieve(draft.id))
    print(client.serverless.queue.deployments.list().data)
