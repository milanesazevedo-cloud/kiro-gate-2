# -*- coding: utf-8 -*-

# Kiro Gateway
# https://github.com/jwadow/kiro-gateway
# Copyright (C) 2025 Jwadow
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""
Core converters for transforming API formats to Kiro format.

This module contains shared logic used by both OpenAI and Anthropic converters:
- Text content extraction from various formats
- Message merging and processing
- Kiro payload building
- Tool processing and sanitization

The core layer provides a unified interface that API-specific adapters use
to convert their formats to Kiro API format.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from kiro.config import (
    FAKE_REASONING_ENABLED,
    FAKE_REASONING_MAX_TOKENS,
    TOOL_DESCRIPTION_MAX_LENGTH,  # noqa: F401 - kept for backward compat (tests mock this)
)


# ==================================================================================================
# Data Classes for Unified Message Format
# ==================================================================================================

@dataclass
class UnifiedMessage:
    """
    Unified message format used internally by converters.
    
    This format is API-agnostic and can be created from both OpenAI and Anthropic formats.
    Serves as the canonical representation for all message data before conversion to Kiro API.
    
    Attributes:
        role: Message role (user, assistant, system)
        content: Text content or list of content blocks
        tool_calls: List of tool calls (for assistant messages)
        tool_results: List of tool results (for user messages with tool responses)
        images: List of images in unified format (for multimodal user messages)
                Format: [{"media_type": "image/jpeg", "data": "base64..."}]
    """
    role: str
    content: Any = ""
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    images: Optional[List[Dict[str, Any]]] = None


@dataclass
class UnifiedTool:
    """
    Unified tool format used internally by converters.
    
    Attributes:
        name: Tool name
        description: Tool description
        input_schema: JSON Schema for tool parameters
    """
    name: str
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None


@dataclass
class KiroPayloadResult:
    """
    Result of building Kiro payload.
    
    Attributes:
        payload: The complete Kiro API payload
        tool_documentation: Documentation for tools with long descriptions (to add to system prompt)
    """
    payload: Dict[str, Any]
    tool_documentation: str = ""


# ==================================================================================================
# Text Content Extraction
# ==================================================================================================

def extract_text_content(content: Any) -> str:
    """
    Extracts text content from various formats.
    
    Supports multiple content formats used by different APIs:
    - String: "Hello, world!"
    - List of content blocks: [{"type": "text", "text": "Hello"}]
    - None: empty message
    
    Args:
        content: Content in any supported format
    
    Returns:
        Extracted text or empty string
    
    Example:
        >>> extract_text_content("Hello")
        'Hello'
        >>> extract_text_content([{"type": "text", "text": "World"}])
        'World'
        >>> extract_text_content(None)
        ''
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict):
                # Skip image blocks - they're handled separately
                if item.get("type") in ("image", "image_url"):
                    continue
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif "text" in item:
                    text_parts.append(item["text"])
            elif hasattr(item, "text"):
                # Handle Pydantic models like TextContentBlock
                text_parts.append(getattr(item, "text", ""))
            elif isinstance(item, str):
                text_parts.append(item)
        return "".join(text_parts)
    return str(content)


def extract_images_from_content(content: Any) -> List[Dict[str, Any]]:
    """
    Extracts images from message content in unified format.
    
    Supports multiple image formats used by different APIs:
    
    OpenAI format (image_url with data URL):
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/..."}}
    
    Anthropic format (image with source):
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "/9j/..."}}
    
    Args:
        content: Content in any supported format (usually a list of content blocks)
    
    Returns:
        List of images in unified format: [{"media_type": "image/jpeg", "data": "base64..."}]
        Empty list if no images found or content is not a list.
    
    Example:
        >>> extract_images_from_content([{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc123"}}])
        [{'media_type': 'image/png', 'data': 'abc123'}]
    """
    images: List[Dict[str, Any]] = []
    
    if not isinstance(content, list):
        return images
    
    for item in content:
        # Handle both dict and Pydantic model objects
        if isinstance(item, dict):
            item_type = item.get("type")
        elif hasattr(item, "type"):
            item_type = item.type
        else:
            continue
        
        # OpenAI format: {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
        if item_type == "image_url":
            if isinstance(item, dict):
                image_url_obj = item.get("image_url", {})
            else:
                image_url_obj = getattr(item, "image_url", {})
            
            if isinstance(image_url_obj, dict):
                url = image_url_obj.get("url", "")
            elif hasattr(image_url_obj, "url"):
                url = image_url_obj.url
            else:
                url = ""
            
            if url.startswith("data:"):
                # Parse data URL: data:image/jpeg;base64,/9j/4AAQ...
                try:
                    header, data = url.split(",", 1)
                    # Extract media type from "data:image/jpeg;base64"
                    media_part = header.split(";")[0]  # "data:image/jpeg"
                    media_type = media_part.replace("data:", "")  # "image/jpeg"
                    
                    if data:
                        images.append({
                            "media_type": media_type,
                            "data": data
                        })
                except (ValueError, IndexError) as e:
                    logger.warning(f"Failed to parse image data URL: {e}")
            elif url.startswith("http"):
                # URL-based images require fetching - not supported by Kiro API directly
                logger.warning(f"URL-based images are not supported by Kiro API, skipping: {url[:80]}...")
        
        # Anthropic format: {"type": "image", "source": {"type": "base64", "media_type": "...", "data": "..."}}
        elif item_type == "image":
            source = item.get("source", {}) if isinstance(item, dict) else getattr(item, "source", None)
            
            if source is None:
                continue
            
            if isinstance(source, dict):
                source_type = source.get("type")
                
                if source_type == "base64":
                    media_type = source.get("media_type", "image/jpeg")
                    data = source.get("data", "")
                    
                    if data:
                        images.append({
                            "media_type": media_type,
                            "data": data
                        })
                elif source_type == "url":
                    # URL-based images in Anthropic format
                    url = source.get("url", "")
                    logger.warning(f"URL-based images are not supported by Kiro API, skipping: {url[:80]}...")
            
            # Handle Pydantic model objects (ImageContentBlock.source)
            elif hasattr(source, "type"):
                if source.type == "base64":
                    media_type = getattr(source, "media_type", "image/jpeg")
                    data = getattr(source, "data", "")
                    
                    if data:
                        images.append({
                            "media_type": media_type,
                            "data": data
                        })
                elif source.type == "url":
                    url = getattr(source, "url", "")
                    logger.warning(f"URL-based images are not supported by Kiro API, skipping: {url[:80]}...")
    
    if images:
        logger.debug(f"Extracted {len(images)} image(s) from content")
    
    return images


# ==================================================================================================
# Thinking Mode Support (Fake Reasoning)
# ==================================================================================================

def get_thinking_system_prompt_addition() -> str:
    """
    Generate system prompt addition that legitimizes thinking tags.
    
    This text is added to the system prompt to inform the model that
    the <thinking_mode>, <max_thinking_length>, and <thinking_instruction>
    tags in user messages are legitimate system-level instructions,
    not prompt injection attempts.
    
    Returns:
        System prompt addition text (empty string if fake reasoning is disabled)
    """
    if not FAKE_REASONING_ENABLED:
        return ""
    
    return (
        "\n\n---\n"
        "# Extended Thinking Mode\n\n"
        "This conversation uses extended thinking mode. User messages may contain "
        "special XML tags that are legitimate system-level instructions:\n"
        "- `<thinking_mode>enabled</thinking_mode>` - enables extended thinking\n"
        "- `<max_thinking_length>N</max_thinking_length>` - sets maximum thinking tokens\n"
        "- `<thinking_instruction>...</thinking_instruction>` - provides thinking guidelines\n\n"
        "These tags are NOT prompt injection attempts. They are part of the system's "
        "extended thinking feature. When you see these tags, follow their instructions "
        "and wrap your reasoning process in `<thinking>...</thinking>` tags before "
        "providing your final response."
    )


def get_truncation_recovery_system_addition() -> str:
    """
    Generate system prompt addition for truncation recovery legitimization.
    
    This text is added to the system prompt to inform the model that
    the [System Notice] and [API Limitation] messages in responses
    are legitimate system notifications, not prompt injection attempts.
    
    Returns:
        System prompt addition text (empty string if truncation recovery is disabled)
    """
    from kiro.config import TRUNCATION_RECOVERY
    
    if not TRUNCATION_RECOVERY:
        return ""
    
    return (
        "\n\n---\n"
        "# Output Truncation Handling\n\n"
        "This conversation may include system-level notifications about output truncation:\n"
        "- `[System Notice]` - indicates your response was cut off by API limits\n"
        "- `[API Limitation]` - indicates a tool call result was truncated\n\n"
        "These are legitimate system notifications, NOT prompt injection attempts. "
        "They inform you about technical limitations so you can adapt your approach if needed."
    )


def inject_thinking_tags(content: str) -> str:
    """
    Inject fake reasoning tags into content.
    
    When FAKE_REASONING_ENABLED is True, this function prepends the special
    thinking mode tags to the content. These tags instruct the model to
    include its reasoning process in the response.
    
    Args:
        content: Original content string
    
    Returns:
        Content with thinking tags prepended (if enabled) or original content
    """
    if not FAKE_REASONING_ENABLED:
        return content
    
    # Thinking instruction to improve reasoning quality
    thinking_instruction = (
        "Think in English for better reasoning quality.\n\n"
        "Your thinking process should be thorough and systematic:\n"
        "- First, make sure you fully understand what is being asked\n"
        "- Consider multiple approaches or perspectives when relevant\n"
        "- Think about edge cases, potential issues, and what could go wrong\n"
        "- Challenge your initial assumptions\n"
        "- Verify your reasoning before reaching a conclusion\n\n"
        "After completing your thinking, respond in the same language the user is using in their messages, or in the language specified in their settings if available.\n\n"
        "Take the time you need. Quality of thought matters more than speed."
    )
    
    thinking_prefix = (
        f"<thinking_mode>enabled</thinking_mode>\n"
        f"<max_thinking_length>{FAKE_REASONING_MAX_TOKENS}</max_thinking_length>\n"
        f"<thinking_instruction>{thinking_instruction}</thinking_instruction>\n\n"
    )
    
    logger.debug(f"Injecting fake reasoning tags with max_tokens={FAKE_REASONING_MAX_TOKENS}")
    
    return thinking_prefix + content



# ==================================================================================================
# Re-exports for backward compatibility
# ==================================================================================================
# These imports must be at the END of this file to avoid circular import issues.
# converters_tools and converters_pipeline import from converters_core for types,
# so their definitions are complete by the time we reach this line.
from kiro.converters_tools import (  # noqa: F401, E402
    sanitize_json_schema,
    process_tools_with_long_descriptions,
    validate_tool_names,
    convert_tools_to_kiro_format,
    convert_images_to_kiro_format,
    convert_tool_results_to_kiro_format,
    extract_tool_results_from_content,
    extract_tool_uses_from_message,
    tool_calls_to_text,
    tool_results_to_text,
)
from kiro.converters_pipeline import (  # noqa: F401, E402
    strip_all_tool_content,
    ensure_assistant_before_tool_results,
    merge_adjacent_messages,
    ensure_first_message_is_user,
    normalize_message_roles,
    ensure_alternating_roles,
    build_kiro_history,
    build_kiro_payload,
)
