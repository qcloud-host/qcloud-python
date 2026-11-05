import os
from qcloud_ai import QCloud

with QCloud() as client:
    print([model.id for model in client.models.list().data])
    response = client.chat.completions.create(
        model=os.environ["QCLOUD_MODEL"],
        messages=[{"role": "user", "content": "Say hello in one sentence."}],
    )
    print(response.choices[0].message.content)
