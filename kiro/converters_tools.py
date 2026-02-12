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

"""Tool processing utilities for Kiro API conversion."""

import json
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

import kiro.converters_core as _converters_core_module
from kiro.converters_core import UnifiedMessage, UnifiedTool, extract_text_content


# ==================================================================================================
# JSON Schema Sanitization
# ==================================================================================================

def sanitize_json_schema(schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Sanitizes JSON Schema from fields that Kiro API doesn't accept.
    
    Kiro API returns 400 "Improperly formed request" error if:
    - required is an empty array []
    - additionalProperties is present in schema
    
    This function recursively processes the schema and removes problematic fields.
    
    Args:
        schema: JSON Schema to sanitize
    
    Returns:
        Sanitized copy of schema
    """
    if not schema:
        return {}
    
    result = {}
    
    for key, value in schema.items():
        # Skip empty required arrays
        if key == "required" and isinstance(value, list) and len(value) == 0:
            continue
        
        # Skip additionalProperties - Kiro API doesn't support it
        if key == "additionalProperties":
            continue
        
        # Recursively process nested objects
        if key == "properties" and isinstance(value, dict):
            result[key] = {
                prop_name: sanitize_json_schema(prop_value) if isinstance(prop_value, dict) else prop_value
                for prop_name, prop_value in value.items()
            }
        elif isinstance(value, dict):
            result[key] = sanitize_json_schema(value)
        elif isinstance(value, list):
            # Process lists (e.g., anyOf, oneOf)
            result[key] = [
                sanitize_json_schema(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    
    return result


# ==================================================================================================
# Tool Processing
# ==================================================================================================

def process_tools_with_long_descriptions(
    tools: Optional[List[UnifiedTool]]
) -> Tuple[Optional[List[UnifiedTool]], str]:
    """
    Processes tools with long descriptions.
    
    Kiro API has a limit on description length in toolSpecification.
    If description exceeds the limit, full description is moved to system prompt,
    and a reference to documentation remains in the tool.
    
    Args:
        tools: List of tools in unified format
    
    Returns:
        Tuple of:
        - List of tools with processed descriptions (or None if tools is empty)
        - String with documentation to add to system prompt (empty if all descriptions are short)
    """
    if not tools:
        return None, ""
    
    # If limit is disabled (0), return tools unchanged
    if _converters_core_module.TOOL_DESCRIPTION_MAX_LENGTH <= 0:
        return tools, ""
    
    tool_documentation_parts = []
    processed_tools = []
    
    for tool in tools:
        description = tool.description or ""
        
        if len(description) <= _converters_core_module.TOOL_DESCRIPTION_MAX_LENGTH:
            # Description is short - leave as is
            processed_tools.append(tool)
        else:
            # Description is too long - move to system prompt
            logger.debug(
                f"Tool '{tool.name}' has long description ({len(description)} chars > {_converters_core_module.TOOL_DESCRIPTION_MAX_LENGTH}), "
                f"moving to system prompt"
            )
            
            # Create documentation for system prompt
            tool_documentation_parts.append(f"## Tool: {tool.name}\n\n{description}")
            
            # Create copy of tool with reference description
            reference_description = f"[Full documentation in system prompt under '## Tool: {tool.name}']"
            
            processed_tool = UnifiedTool(
                name=tool.name,
                description=reference_description,
                input_schema=tool.input_schema
            )
            processed_tools.append(processed_tool)
    
    # Form final documentation
    tool_documentation = ""
    if tool_documentation_parts:
        tool_documentation = (
            "\n\n---\n"
            "# Tool Documentation\n"
            "The following tools have detailed documentation that couldn't fit in the tool definition.\n\n"
            + "\n\n---\n\n".join(tool_documentation_parts)
        )
    
    return processed_tools if processed_tools else None, tool_documentation


def validate_tool_names(tools: Optional[List[UnifiedTool]]) -> None:
    """
    Validates tool names against Kiro API 64-character limit.
    
    Logs WARNING for each problematic tool and raises ValueError
    with complete list of violations.
    
    Args:
        tools: List of tools to validate
    
    Raises:
        ValueError: If any tool name exceeds 64 characters
    
    Example:
        >>> validate_tool_names([UnifiedTool(name="short_name", description="test")])
        # No error
        >>> validate_tool_names([UnifiedTool(name="a" * 70, description="test")])
        # Raises ValueError with detailed message
    """
    if not tools:
        return
    
    problematic_tools = []
    for tool in tools:
        if len(tool.name) > 64:
            problematic_tools.append((tool.name, len(tool.name)))
    
    if problematic_tools:
        # Build detailed error message for client (no logging here - routes will log)
        tool_list = "\n".join([
            f"  - '{name}' ({length} characters)"
            for name, length in problematic_tools
        ])
        
        raise ValueError(
            f"Tool name(s) exceed Kiro API limit of 64 characters:\n"
            f"{tool_list}\n\n"
            f"Solution: Use shorter tool names (max 64 characters).\n"
            f"Example: 'get_user_data' instead of 'get_authenticated_user_profile_data_with_extended_information_about_it'"
        )


def convert_tools_to_kiro_format(tools: Optional[List[UnifiedTool]]) -> List[Dict[str, Any]]:
    """
    Converts unified tools to Kiro API format.
    
    Args:
        tools: List of tools in unified format
    
    Returns:
        List of tools in Kiro toolSpecification format
    """
    if not tools:
        return []
    
    kiro_tools = []
    for tool in tools:
        # Sanitize parameters from fields that Kiro API doesn't accept
        sanitized_params = sanitize_json_schema(tool.input_schema)
        
        # Kiro API requires non-empty description
        description = tool.description
        if not description or not description.strip():
            description = f"Tool: {tool.name}"
            logger.debug(f"Tool '{tool.name}' has empty description, using placeholder")
        
        kiro_tools.append({
            "toolSpecification": {
                "name": tool.name,
                "description": description,
                "inputSchema": {"json": sanitized_params}
            }
        })
    
    return kiro_tools


# ==================================================================================================
# Image Conversion to Kiro Format
# ==================================================================================================

def convert_images_to_kiro_format(images: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Converts unified images to Kiro API format.
    
    Unified format: [{"media_type": "image/jpeg", "data": "base64..."}]
    Kiro format: [{"format": "jpeg", "source": {"bytes": "base64..."}}]
    
    IMPORTANT: Images must be placed directly in userInputMessage.images,
    NOT in userInputMessageContext.images. This matches the native Kiro IDE format.
    
    Also handles the case where data contains a full data URL (data:image/jpeg;base64,...)
    by stripping the prefix and extracting pure base64.
    
    Args:
        images: List of images in unified format
    
    Returns:
        List of images in Kiro format, ready for userInputMessage.images
    
    Example:
        >>> convert_images_to_kiro_format([{"media_type": "image/png", "data": "abc123"}])
        [{'format': 'png', 'source': {'bytes': 'abc123'}}]
    """
    if not images:
        return []
    
    kiro_images = []
    for img in images:
        media_type = img.get("media_type", "image/jpeg")
        data = img.get("data", "")
        
        if not data:
            logger.warning("Skipping image with empty data")
            continue
        
        # Strip data URL prefix if present (some clients send "data:image/jpeg;base64,..." in data field)
        # Kiro API expects pure base64 without the prefix
        if data.startswith("data:"):
            try:
                header, actual_data = data.split(",", 1)
                # Extract media type from header if present
                media_part = header.split(";")[0]  # "data:image/jpeg"
                extracted_media_type = media_part.replace("data:", "")
                if extracted_media_type:
                    media_type = extracted_media_type
                data = actual_data
                logger.debug(f"Stripped data URL prefix, extracted media_type: {media_type}")
            except (ValueError, IndexError) as e:
                logger.warning(f"Failed to parse data URL prefix: {e}")
        
        # Extract format from media_type: "image/jpeg" -> "jpeg"
        format_str = media_type.split("/")[-1] if "/" in media_type else media_type
        
        kiro_images.append({
            "format": format_str,
            "source": {
                "bytes": data
            }
        })
    
    if kiro_images:
        logger.debug(f"Converted {len(kiro_images)} image(s) to Kiro format")
    
    return kiro_images


# ==================================================================================================
# Tool Results and Tool Uses Extraction
# ==================================================================================================

def convert_tool_results_to_kiro_format(tool_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Converts unified tool results to Kiro API format.
    
    Unified format: {"type": "tool_result", "tool_use_id": "...", "content": "..."}
    Kiro format: {"content": [{"text": "..."}], "status": "success", "toolUseId": "..."}
    
    Args:
        tool_results: List of tool results in unified format
    
    Returns:
        List of tool results in Kiro format
    """
    kiro_results = []
    for tr in tool_results:
        content = tr.get("content", "")
        if isinstance(content, str):
            content_text = content
        else:
            content_text = extract_text_content(content)
        
        # Ensure content is not empty - Kiro API requires non-empty content
        if not content_text:
            content_text = "(empty result)"
        
        kiro_results.append({
            "content": [{"text": content_text}],
            "status": "success",
            "toolUseId": tr.get("tool_use_id", "")
        })
    
    return kiro_results


def extract_tool_results_from_content(content: Any) -> List[Dict[str, Any]]:
    """
    Extracts tool results from message content.
    
    Looks for content blocks with type="tool_result" and converts them
    to Kiro API format.
    
    Args:
        content: Message content (can be a list of content blocks)
    
    Returns:
        List of tool results in Kiro format
    """
    tool_results = []
    
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                tool_results.append({
                    "content": [{"text": extract_text_content(item.get("content", "")) or "(empty result)"}],
                    "status": "success",
                    "toolUseId": item.get("tool_use_id", "")
                })
    
    return tool_results


def extract_tool_uses_from_message(
    content: Any,
    tool_calls: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    """
    Extracts tool uses from assistant message.
    
    Looks for tool calls in both:
    - tool_calls field (OpenAI format)
    - content blocks with type="tool_use" (Anthropic format)
    
    Args:
        content: Message content
        tool_calls: List of tool calls (OpenAI format)
    
    Returns:
        List of tool uses in Kiro format
    """
    tool_uses = []
    
    # From tool_calls field (OpenAI format or unified format from Anthropic)
    if tool_calls:
        for tc in tool_calls:
            if isinstance(tc, dict):
                func = tc.get("function", {})
                arguments = func.get("arguments", "{}")
                # Handle both string (OpenAI) and dict (Anthropic unified) formats
                if isinstance(arguments, str):
                    input_data = json.loads(arguments) if arguments else {}
                else:
                    input_data = arguments if arguments else {}
                tool_uses.append({
                    "name": func.get("name", ""),
                    "input": input_data,
                    "toolUseId": tc.get("id", "")
                })
    
    # From content blocks (Anthropic format)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                tool_uses.append({
                    "name": item.get("name", ""),
                    "input": item.get("input", {}),
                    "toolUseId": item.get("id", "")
                })
    
    return tool_uses


# ==================================================================================================
# Tool Content to Text Conversion (for stripping when no tools defined)
# ==================================================================================================

def tool_calls_to_text(tool_calls: List[Dict[str, Any]]) -> str:
    """
    Converts tool_calls to human-readable text representation.
    
    This is used when stripping tool content from messages (when no tools are defined).
    Instead of losing the context, we convert tool calls to text so the model
    can still understand what happened in the conversation.
    
    Args:
        tool_calls: List of tool calls in unified format
    
    Returns:
        Text representation of tool calls
    
    Example:
        >>> tool_calls_to_text([{"id": "call_123", "function": {"name": "bash", "arguments": '{"command": "ls"}'}}])
        '[Tool: bash] (call_123)\\n{"command": "ls"}'
    """
    if not tool_calls:
        return ""
    
    parts = []
    for tc in tool_calls:
        func = tc.get("function", {})
        name = func.get("name", "unknown")
        arguments = func.get("arguments", "{}")
        tool_id = tc.get("id", "")
        
        # Format: [Tool: name] (id)\narguments
        if tool_id:
            parts.append(f"[Tool: {name} ({tool_id})]\n{arguments}")
        else:
            parts.append(f"[Tool: {name}]\n{arguments}")
    
    return "\n\n".join(parts)


def tool_results_to_text(tool_results: List[Dict[str, Any]]) -> str:
    """
    Converts tool_results to human-readable text representation.
    
    This is used when stripping tool content from messages (when no tools are defined).
    Instead of losing the context, we convert tool results to text so the model
    can still understand what happened in the conversation.
    
    Args:
        tool_results: List of tool results in unified format
    
    Returns:
        Text representation of tool results
    
    Example:
        >>> tool_results_to_text([{"tool_use_id": "call_123", "content": "file1.txt\\nfile2.txt"}])
        '[Tool Result] (call_123)\\nfile1.txt\\nfile2.txt'
    """
    if not tool_results:
        return ""
    
    parts = []
    for tr in tool_results:
        content = tr.get("content", "")
        tool_use_id = tr.get("tool_use_id", "")
        
        if isinstance(content, str):
            content_text = content
        else:
            content_text = extract_text_content(content)
        
        # Use placeholder if content is empty
        if not content_text:
            content_text = "(empty result)"
        
        # Format: [Tool Result] (id)\ncontent
        if tool_use_id:
            parts.append(f"[Tool Result ({tool_use_id})]\n{content_text}")
        else:
            parts.append(f"[Tool Result]\n{content_text}")
    
    return "\n\n".join(parts)


# ==================================================================================================
# Message Merging
# ==================================================================================================
