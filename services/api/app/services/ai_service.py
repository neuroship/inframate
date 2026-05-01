from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

SYSTEM_PROMPT = """You are an expert Terraform assistant integrated into Inframate, a Terraform UI tool.
Help users with:
- Understanding their Terraform configuration and resources
- Diagnosing and fixing errors from terraform plan/apply
- Writing and modifying Terraform HCL code
- Best practices for infrastructure as code
- AWS (and other provider) resource configuration

Be concise and provide actionable solutions. When showing code, use HCL syntax."""

SIDEBAR_PROMPT = """You are an expert Terraform assistant integrated into Inframate.
You have access to the user's Terraform files and infrastructure state.

When suggesting file changes, use this exact format so the user can apply them:

File: <filename>
```hcl
<complete updated file content>
```

Always show the COMPLETE file content (not partial diffs) so it can be applied directly.
Be concise. Focus on actionable fixes and clear explanations."""

DIAGNOSE_PROMPT = """You are an expert Terraform troubleshooter integrated into Inframate.
A user just ran a terraform command that produced errors. You have access to the full workspace files.

Analyze the output and respond in markdown with:

1. **What went wrong** — brief root cause
2. **How to fix it** — specific, actionable steps
3. **Corrected code** — if the fix involves HCL changes, show the COMPLETE corrected file content
4. **Commands to run** — if the fix requires CLI commands (terraform import, terraform state rm, aws cli, etc.)

IMPORTANT: When showing code fixes, use this exact format so the user can apply them directly:

File: <filename>
```hcl
<complete updated file content>
```

When suggesting commands to run, use bash code blocks:
```bash
terraform import aws_s3_bucket.foo my-bucket
```

Always show the COMPLETE file content (not partial snippets) so it can be applied as a replacement.
Be concise and direct. Use markdown formatting for readability."""


SUMMARIZE_PROMPT = """You are an expert Terraform assistant. The user has a terraform plan with pending changes.

Analyze the resource changes below and provide a clear, prioritized summary:

1. List changes from MOST IMPORTANT (destructive/risky) to LEAST IMPORTANT (safe/minor)
2. For each change, briefly explain what it does and its potential impact
3. Flag any risky operations (destroys, replacements, security group changes, etc.)

Use markdown formatting. Be concise — one or two lines per resource. Group by risk level:
- **Critical** — destroys, replacements, security changes
- **Important** — updates to core resources
- **Safe** — creates, minor updates

Skip no-op resources unless there are very few changes total."""


def _get_client(config: dict) -> AsyncOpenAI | None:
    token = config.get("api_token")
    if not token:
        return None
    endpoint = config.get("endpoint") or "https://api.openai.com/v1"
    return AsyncOpenAI(api_key=token, base_url=endpoint)


async def chat_stream(
    message: str, context: str | None, config: dict
) -> AsyncGenerator[str, None]:
    client = _get_client(config)
    if not client:
        yield "Error: AI not configured. Open Settings in the navbar to add your OpenAI endpoint and token."
        return

    model = config.get("model") or "gpt-4o"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append(
            {"role": "system", "content": f"Current Terraform context:\n{context}"}
        )
    messages.append({"role": "user", "content": message})

    stream = await client.chat.completions.create(
        model=model, messages=messages, stream=True
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


async def chat_session_stream(
    history: list[dict], context: str | None, config: dict
) -> AsyncGenerator[str, None]:
    client = _get_client(config)
    if not client:
        yield "Error: AI not configured. Open Settings in the navbar to add your OpenAI endpoint and token."
        return

    model = config.get("model") or "gpt-4o"
    messages = [{"role": "system", "content": SIDEBAR_PROMPT}]
    if context:
        messages.append(
            {"role": "system", "content": f"Workspace Terraform files:\n{context}"}
        )
    # Append conversation history (user/assistant messages)
    for msg in history:
        role = msg.role if hasattr(msg, "role") else msg.get("role", "user")
        content = msg.content if hasattr(msg, "content") else msg.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})

    stream = await client.chat.completions.create(
        model=model, messages=messages, stream=True
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


async def diagnose_stream(
    command: str, output: str, workspace_context: str | None, config: dict
) -> AsyncGenerator[str, None]:
    client = _get_client(config)
    if not client:
        yield "Error: AI not configured. Open Settings in the navbar to add your OpenAI endpoint and token."
        return

    model = config.get("model") or "gpt-4o"
    messages = [{"role": "system", "content": DIAGNOSE_PROMPT}]
    if workspace_context:
        messages.append(
            {"role": "system", "content": f"Workspace context:\n{workspace_context}"}
        )
    messages.append(
        {
            "role": "user",
            "content": f"Command: terraform {command}\n\nOutput:\n```\n{output}\n```",
        }
    )

    stream = await client.chat.completions.create(
        model=model, messages=messages, stream=True
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content


async def summarize_plan_stream(
    resources: list[dict], config: dict
) -> AsyncGenerator[str, None]:
    client = _get_client(config)
    if not client:
        yield "Error: AI not configured. Open Settings to add your AI endpoint and token."
        return

    lines = []
    for r in resources:
        action = r.get("action", "no-op")
        if action == "no-op":
            continue
        rtype = r.get("display_type") or r.get("resource_type", "unknown")
        name = r.get("resource_name", "unnamed")
        address = r.get("id", "")

        line = f'- {action.upper()}: {rtype} "{name}" ({address})'

        before = r.get("before", {}) or {}
        after = r.get("after", {}) or {}
        if action in ("update", "replace") and before and after:
            changes = []
            for k in sorted(set(list(before.keys()) + list(after.keys()))):
                if k in ("tags", "tags_all", "timeouts"):
                    continue
                bv, av = before.get(k), after.get(k)
                if bv != av:
                    changes.append(f"  {k}: {bv} -> {av}")
            if changes:
                line += "\n" + "\n".join(changes[:10])
        elif action == "create" and after:
            attrs = [
                f"  {k}: {v}"
                for k, v in list(after.items())[:5]
                if v is not None and k not in ("tags", "tags_all", "timeouts")
            ]
            if attrs:
                line += "\n" + "\n".join(attrs)

        lines.append(line)

    if not lines:
        yield "No pending changes to summarize. All resources are up to date."
        return

    plan_text = "\n".join(lines)
    model = config.get("model") or "gpt-4o"
    messages = [
        {"role": "system", "content": SUMMARIZE_PROMPT},
        {
            "role": "user",
            "content": f"Here are the planned changes ({len(lines)} resources with changes):\n\n{plan_text}",
        },
    ]

    stream = await client.chat.completions.create(
        model=model, messages=messages, stream=True
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
