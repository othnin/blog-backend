"""Shared Lexical JSON utilities for blog and recipes."""
import json


def lexical_to_text(content_json: str) -> str:
    """Extract plain text from Lexical JSON content by walking the node tree."""
    try:
        data = json.loads(content_json)
    except (json.JSONDecodeError, TypeError):
        return ''

    parts = []

    def walk(node):
        if isinstance(node, dict):
            if node.get('type') == 'text':
                text = node.get('text', '')
                if text:
                    parts.append(text)
            else:
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return ' '.join(parts)
