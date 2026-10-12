"""Una sola petición Azure OpenAI, autenticada sin claves y sin reintentos."""
import os
from urllib.parse import urlparse, quote

import httpx
from azure.identity import AzureCliCredential


def generate(messages: list[dict]) -> dict:
    endpoint = os.getenv('AZURE_OPENAI_ENDPOINT', '').rstrip('/')
    parsed = urlparse(endpoint)
    if (parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.openai.azure.com')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path or parsed.port not in (None, 443)):
        raise ValueError('Configura AZURE_OPENAI_ENDPOINT con la URL HTTPS de tu recurso Azure OpenAI')
    deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', 'chat-practicas')
    # Esta fase usa la sesión local de az login. ACA se conectará en una fase posterior.
    with AzureCliCredential() as credential:
        token = credential.get_token('https://cognitiveservices.azure.com/.default').token
        with httpx.Client(timeout=45, follow_redirects=False) as client:
            response = client.post(
                f'{endpoint}/openai/deployments/{quote(deployment, safe="")}/chat/completions',
                params={'api-version': '2024-10-21'},
                headers={'Authorization': f'Bearer {token}'},
                json={'messages': messages, 'max_completion_tokens': 500, 'temperature': 0.2})
            response.raise_for_status()
            data = response.json()
    choice = data['choices'][0]
    return {'answer': choice['message'].get('content') or '',
            'finish_reason': choice['finish_reason'], 'usage': data.get('usage', {}),
            'model': data.get('model'), 'deployment': deployment}
