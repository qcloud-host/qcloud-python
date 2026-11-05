import os
from qcloud_ai import QCloud

# Select a model that supports tools and structured output.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Look up the weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
        },
    }
]
with QCloud() as client:
    result = client.chat.completions.create(
        model=os.environ["QCLOUD_MODEL"],
        messages=[{"role": "user", "content": "What is the weather in Athens?"}],
        tools=TOOLS,
        tool_choice="auto",
    )
    # Inspect and validate tool arguments before your application executes a tool.
    print(result.choices[0].message.tool_calls)
    result = client.chat.completions.create(
        model=os.environ["QCLOUD_MODEL"],
        messages=[
            {"role": "user", "content": "Return a JSON object with a greeting field."}
        ],
        response_format={"type": "json_object"},
    )
    print(result.choices[0].message.content)
