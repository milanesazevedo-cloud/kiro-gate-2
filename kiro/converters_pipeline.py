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

"""Message normalization and Kiro payload building pipeline."""

import json
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from kiro.config import FAKE_REASONING_ENABLED, FAKE_REASONING_MAX_TOKENS
from kiro.converters_core import (
    UnifiedMessage, UnifiedTool, KiroPayloadResult,
    extract_text_content, extract_images_from_content,
    get_thinking_system_prompt_addition, get_truncation_recovery_system_addition,
    inject_thinking_tags,
)
from kiro.converters_tools import (
    process_tools_with_long_descriptions, validate_tool_names,
    convert_tools_to_kiro_format, convert_images_to_kiro_format,
    convert_tool_results_to_kiro_format, extract_tool_results_from_content,
    extract_tool_uses_from_message, tool_calls_to_text, tool_results_to_text,
)


def strip_all_tool_content(messages: List[UnifiedMessage]) -> Tuple[List[UnifiedMessage], bool]:
    """
    Strips ALL tool-related content from messages, converting it to text representation.
    
    This is used when no tools are defined in the request. Kiro API rejects
    requests that have toolResults but no tools defined.
    
    Instead of simply removing tool content, this function converts tool_calls
    and tool_results to human-readable text, preserving the context for
    summarization and other use cases.
    
    Args:
        messages: List of messages in unified format
    
    Returns:
        Tuple of:
        - List of messages with tool content converted to text
        - Boolean indicating whether any tool content was converted
    """
    if not messages:
        return [], False
    
    result = []
    total_tool_calls_stripped = 0
    total_tool_results_stripped = 0
    
    for msg in messages:
        # Check if this message has any tool content
        has_tool_calls = bool(msg.tool_calls)
        has_tool_results = bool(msg.tool_results)
        
        if has_tool_calls or has_tool_results:
            if has_tool_calls:
                total_tool_calls_stripped += len(msg.tool_calls)
            if has_tool_results:
                total_tool_results_stripped += len(msg.tool_results)
            
            # Start with existing text content
            existing_content = extract_text_content(msg.content)
            content_parts = []
            
            if existing_content:
                content_parts.append(existing_content)
            
            # Convert tool_calls to text (for assistant messages)
            if has_tool_calls:
                tool_text = tool_calls_to_text(msg.tool_calls)
                if tool_text:
                    content_parts.append(tool_text)
            
            # Convert tool_results to text (for user messages)
            if has_tool_results:
                result_text = tool_results_to_text(msg.tool_results)
                if result_text:
                    content_parts.append(result_text)
            
            # Join all parts with double newline
            content = "\n\n".join(content_parts) if content_parts else "(empty)"
            
            # Create a copy of the message without tool content but with text representation
            # IMPORTANT: Preserve images from the original message (e.g., screenshots from MCP tools)
            cleaned_msg = UnifiedMessage(
                role=msg.role,
                content=content,
                tool_calls=None,
                tool_results=None,
                images=msg.images
            )
            result.append(cleaned_msg)
        else:
            result.append(msg)
    
    had_tool_content = total_tool_calls_stripped > 0 or total_tool_results_stripped > 0
    
    # Log summary once (DEBUG level - this is normal for clients like Cline/Roo/Cursor)
    if had_tool_content:
        logger.debug(
            f"Converted tool content to text (no tools defined): "
            f"{total_tool_calls_stripped} tool_calls, {total_tool_results_stripped} tool_results"
        )
    
    return result, had_tool_content


def ensure_assistant_before_tool_results(messages: List[UnifiedMessage]) -> Tuple[List[UnifiedMessage], bool]:
    """
    Ensures that messages with tool_results have a preceding assistant message with tool_calls.
    
    Kiro API requires that when toolResults are present, there must be a preceding
    assistantResponseMessage with toolUses. Some clients (like Cline/Roo/Cursor) may send
    truncated conversations where the assistant message is missing.
    
    Since we don't know the original tool name and arguments when the assistant message
    is missing, we cannot create a valid synthetic assistant message. Instead, we convert
    the tool_results to text representation and append to the message content, preserving
    the context for the model while avoiding Kiro API rejection.
    
    Args:
        messages: List of messages in unified format
    
    Returns:
        Tuple of:
        - List of messages with orphaned tool_results converted to text
        - Boolean indicating whether any tool_results were converted (used to skip thinking tag injection)
    """
    if not messages:
        return [], False
    
    result = []
    converted_any_tool_results = False
    
    for msg in messages:
        # Check if this message has tool_results
        if msg.tool_results:
            # Check if the previous message is an assistant with tool_calls
            has_preceding_assistant = (
                result and
                result[-1].role == "assistant" and
                result[-1].tool_calls
            )
            
            if not has_preceding_assistant:
                # We cannot create a valid synthetic assistant message because we don't know
                # the original tool name and arguments. Kiro API validates tool names.
                # Convert tool_results to text to preserve context for the model.
                logger.debug(
                    f"Converting {len(msg.tool_results)} orphaned tool_results to text "
                    f"(no preceding assistant message with tool_calls). "
                    f"Tool IDs: {[tr.get('tool_use_id', 'unknown') for tr in msg.tool_results]}"
                )
                
                # Convert tool_results to text representation
                tool_results_text = tool_results_to_text(msg.tool_results)
                
                # Append to existing content
                original_content = extract_text_content(msg.content) or ""
                if original_content and tool_results_text:
                    new_content = f"{original_content}\n\n{tool_results_text}"
                elif tool_results_text:
                    new_content = tool_results_text
                else:
                    new_content = original_content
                
                # Create a copy of the message with tool_results converted to text
                cleaned_msg = UnifiedMessage(
                    role=msg.role,
                    content=new_content,
                    tool_calls=msg.tool_calls,
                    tool_results=None,  # Remove orphaned tool_results (now in text)
                    images=msg.images
                )
                result.append(cleaned_msg)
                converted_any_tool_results = True
                continue
        
        result.append(msg)
    
    return result, converted_any_tool_results


def merge_adjacent_messages(messages: List[UnifiedMessage]) -> List[UnifiedMessage]:
    """
    Merges adjacent messages with the same role.
    
    Kiro API does not accept multiple consecutive messages from the same role.
    This function merges such messages into one.
    
    Args:
        messages: List of messages in unified format
    
    Returns:
        List of messages with merged adjacent messages
    """
    if not messages:
        return []
    
    merged = []
    # Statistics for summary logging
    merge_counts = {"user": 0, "assistant": 0}
    total_tool_calls_merged = 0
    total_tool_results_merged = 0
    
    for msg in messages:
        if not merged:
            merged.append(msg)
            continue
        
        last = merged[-1]
        if msg.role == last.role:
            # Compute merged content (immutable)
            if isinstance(last.content, list) and isinstance(msg.content, list):
                new_content = last.content + msg.content
            elif isinstance(last.content, list):
                new_content = last.content + [{"type": "text", "text": extract_text_content(msg.content)}]
            elif isinstance(msg.content, list):
                new_content = [{"type": "text", "text": extract_text_content(last.content)}] + msg.content
            else:
                last_text = extract_text_content(last.content)
                current_text = extract_text_content(msg.content)
                new_content = f"{last_text}\n{current_text}"

            # Compute merged tool_calls for assistant messages (immutable)
            new_tool_calls = last.tool_calls
            if msg.role == "assistant" and msg.tool_calls:
                base = list(last.tool_calls) if last.tool_calls else []
                new_tool_calls = base + list(msg.tool_calls)
                total_tool_calls_merged += len(msg.tool_calls)

            # Compute merged tool_results for user messages (immutable)
            new_tool_results = last.tool_results
            if msg.role == "user" and msg.tool_results:
                base = list(last.tool_results) if last.tool_results else []
                new_tool_results = base + list(msg.tool_results)
                total_tool_results_merged += len(msg.tool_results)

            # Replace last entry with a new immutable object
            from dataclasses import replace as dc_replace
            merged[-1] = dc_replace(
                last,
                content=new_content,
                tool_calls=new_tool_calls,
                tool_results=new_tool_results,
            )

            # Count merges by role
            if msg.role in merge_counts:
                merge_counts[msg.role] += 1
        else:
            merged.append(msg)
    
    # Log summary if any merges occurred
    total_merges = sum(merge_counts.values())
    if total_merges > 0:
        parts = []
        for role, count in merge_counts.items():
            if count > 0:
                parts.append(f"{count} {role}")
        merge_summary = ", ".join(parts)
        
        extras = []
        if total_tool_calls_merged > 0:
            extras.append(f"{total_tool_calls_merged} tool_calls")
        if total_tool_results_merged > 0:
            extras.append(f"{total_tool_results_merged} tool_results")
        
        if extras:
            logger.debug(f"Merged {total_merges} adjacent messages ({merge_summary}), including {', '.join(extras)}")
        else:
            logger.debug(f"Merged {total_merges} adjacent messages ({merge_summary})")
    
    return merged


def ensure_first_message_is_user(messages: List[UnifiedMessage]) -> List[UnifiedMessage]:
    """
    Ensures that the first message in the conversation is from user role.
    
    Kiro API requires conversations to start with a user message. If the first
    message is from assistant (or any other non-user role), we prepend a minimal
    synthetic user message.
    
    This matches LiteLLM behavior for Anthropic API compatibility and fixes
    issue #60 where conversations starting with assistant messages cause
    "Improperly formed request" errors.
    
    Args:
        messages: List of messages in unified format
    
    Returns:
        List of messages with guaranteed user-first order
    
    Example:
        >>> messages = [
        ...     UnifiedMessage(role="assistant", content="Hello"),
        ...     UnifiedMessage(role="user", content="Hi")
        ... ]
        >>> result = ensure_first_message_is_user(messages)
        >>> result[0].role
        'user'
        >>> result[0].content
        '(empty)'
    """
    if not messages:
        return messages
    
    if messages[0].role != "user":
        logger.debug(
            f"First message is '{messages[0].role}', prepending synthetic user message "
            f"(Kiro API requires conversations to start with user)"
        )
        
        # Create minimal synthetic user message (matches LiteLLM behavior)
        # Using "(empty)" as minimal valid content to avoid disrupting conversation context
        synthetic_user = UnifiedMessage(
            role="user",
            content="(empty)"
        )
        
        return [synthetic_user] + messages
    
    return messages


def normalize_message_roles(messages: List[UnifiedMessage]) -> List[UnifiedMessage]:
    """
    Normalizes unknown message roles to 'user'.
    
    Kiro API only supports 'user' and 'assistant' roles in history.
    Any other role (e.g., 'developer', 'system') is converted to 'user'
    to maintain compatibility.
    
    This normalization MUST happen before ensure_alternating_roles()
    to ensure consecutive messages with unknown roles are properly detected
    and synthetic assistant messages are inserted between them.
    
    Args:
        messages: List of messages in unified format
    
    Returns:
        List of messages with normalized roles
    
    Example:
        >>> messages = [
        ...     UnifiedMessage(role="developer", content="Context 1"),
        ...     UnifiedMessage(role="developer", content="Context 2"),
        ...     UnifiedMessage(role="user", content="Question")
        ... ]
        >>> result = normalize_message_roles(messages)
        >>> [msg.role for msg in result]
        ['user', 'user', 'user']
    """
    if not messages:
        return messages
    
    normalized = []
    converted_count = 0
    
    for msg in messages:
        if msg.role not in ("user", "assistant"):
            logger.debug(f"Normalizing role '{msg.role}' to 'user'")
            normalized_msg = UnifiedMessage(
                role="user",
                content=msg.content,
                tool_calls=msg.tool_calls,
                tool_results=msg.tool_results,
                images=msg.images
            )
            normalized.append(normalized_msg)
            converted_count += 1
        else:
            normalized.append(msg)
    
    if converted_count > 0:
        logger.debug(f"Normalized {converted_count} message(s) with unknown roles to 'user'")
    
    return normalized


def ensure_alternating_roles(messages: List[UnifiedMessage]) -> List[UnifiedMessage]:
    """
    Ensures alternating user/assistant roles by inserting synthetic assistant messages.
    
    Kiro API requires alternating userInputMessage and assistantResponseMessage.
    When consecutive user messages are detected, synthetic assistant messages
    with "(empty)" placeholder are inserted between them to maintain alternation.
    
    This fixes multiple unknown roles (converted to user)
    create consecutive userInputMessage entries that violate Kiro API requirements.
    
    Args:
        messages: List of messages in unified format
    
    Returns:
        List of messages with synthetic assistant messages inserted where needed
    
    Example:
        >>> messages = [
        ...     UnifiedMessage(role="user", content="First"),
        ...     UnifiedMessage(role="user", content="Second"),
        ...     UnifiedMessage(role="user", content="Third")
        ... ]
        >>> result = ensure_alternating_roles(messages)
        >>> len(result)
        5  # 3 user + 2 synthetic assistant
        >>> result[1].role
        'assistant'
        >>> result[1].content
        '(empty)'
    """
    if not messages or len(messages) < 2:
        return messages
    
    result = [messages[0]]
    synthetic_count = 0
    
    for msg in messages[1:]:
        prev_role = result[-1].role
        
        # If both current and previous are user → insert synthetic assistant
        if msg.role == "user" and prev_role == "user":
            synthetic_assistant = UnifiedMessage(
                role="assistant",
                content="(empty)"  # Consistent with build_kiro_history() placeholder
            )
            result.append(synthetic_assistant)
            synthetic_count += 1
        
        result.append(msg)
    
    if synthetic_count > 0:
        logger.debug(f"Inserted {synthetic_count} synthetic assistant message(s) to ensure alternation")
    
    return result


# ==================================================================================================
# Kiro History Building
# ==================================================================================================

def build_kiro_history(messages: List[UnifiedMessage], model_id: str) -> List[Dict[str, Any]]:
    """
    Builds history array for Kiro API from unified messages.
    
    Kiro API expects alternating userInputMessage and assistantResponseMessage.
    This function converts unified format to Kiro format.
    
    All messages should have 'user' or 'assistant' roles at this point,
    as unknown roles are normalized earlier in the pipeline by normalize_message_roles().
    
    Args:
        messages: List of messages in unified format (with normalized roles)
        model_id: Internal Kiro model ID
    
    Returns:
        List of dictionaries for history field in Kiro API
    """
    history = []
    
    for msg in messages:
        if msg.role == "user":
            content = extract_text_content(msg.content)
            
            # Fallback for empty content - Kiro API requires non-empty content
            if not content:
                content = "(empty)"
            
            user_input = {
                "content": content,
                "modelId": model_id,
                "origin": "AI_EDITOR",
            }
            
            # Process images - extract from message or content
            # IMPORTANT: images go directly into userInputMessage, NOT into userInputMessageContext
            # This matches the native Kiro IDE format
            images = msg.images or extract_images_from_content(msg.content)
            if images:
                kiro_images = convert_images_to_kiro_format(images)
                if kiro_images:
                    user_input["images"] = kiro_images
            
            # Build userInputMessageContext for tools and toolResults only
            user_input_context: Dict[str, Any] = {}
            
            # Process tool_results - convert to Kiro format if present
            if msg.tool_results:
                kiro_tool_results = convert_tool_results_to_kiro_format(msg.tool_results)
                if kiro_tool_results:
                    user_input_context["toolResults"] = kiro_tool_results
            else:
                # Try to extract from content (already in Kiro format)
                tool_results = extract_tool_results_from_content(msg.content)
                if tool_results:
                    user_input_context["toolResults"] = tool_results
            
            # Add context if not empty (contains toolResults only, not images)
            if user_input_context:
                user_input["userInputMessageContext"] = user_input_context
            
            history.append({"userInputMessage": user_input})
            
        elif msg.role == "assistant":
            content = extract_text_content(msg.content)
            
            # Fallback for empty content - Kiro API requires non-empty content
            if not content:
                content = "(empty)"
            
            assistant_response = {"content": content}
            
            # Process tool_calls
            tool_uses = extract_tool_uses_from_message(msg.content, msg.tool_calls)
            if tool_uses:
                assistant_response["toolUses"] = tool_uses
            
            history.append({"assistantResponseMessage": assistant_response})
    
    return history


# ==================================================================================================
# Main Payload Building
# ==================================================================================================

def build_kiro_payload(
    messages: List[UnifiedMessage],
    system_prompt: str,
    model_id: str,
    tools: Optional[List[UnifiedTool]],
    conversation_id: str,
    profile_arn: str,
    inject_thinking: bool = True
) -> KiroPayloadResult:
    """
    Builds complete payload for Kiro API from unified data.
    
    This is the main function that assembles the Kiro API payload from
    API-agnostic unified message and tool formats.
    
    Args:
        messages: List of messages in unified format (without system messages)
        system_prompt: Already extracted system prompt
        model_id: Internal Kiro model ID
        tools: List of tools in unified format (or None)
        conversation_id: Unique conversation ID
        profile_arn: AWS CodeWhisperer profile ARN
        inject_thinking: Whether to inject thinking tags (default True)
    
    Returns:
        KiroPayloadResult with payload and tool documentation
    
    Raises:
        ValueError: If there are no messages to send
    """
    # Process tools with long descriptions
    processed_tools, tool_documentation = process_tools_with_long_descriptions(tools)
    
    # Validate tool names against Kiro API 64-character limit
    validate_tool_names(processed_tools)
    
    # Add tool documentation to system prompt if present
    full_system_prompt = system_prompt
    if tool_documentation:
        full_system_prompt = full_system_prompt + tool_documentation if full_system_prompt else tool_documentation.strip()
    
    # Add thinking mode legitimization to system prompt if enabled
    thinking_system_addition = get_thinking_system_prompt_addition()
    if thinking_system_addition:
        full_system_prompt = full_system_prompt + thinking_system_addition if full_system_prompt else thinking_system_addition.strip()
    
    # Add truncation recovery legitimization to system prompt if enabled
    truncation_system_addition = get_truncation_recovery_system_addition()
    if truncation_system_addition:
        full_system_prompt = full_system_prompt + truncation_system_addition if full_system_prompt else truncation_system_addition.strip()
    
    # If no tools are defined, strip ALL tool-related content from messages
    # Kiro API rejects requests with toolResults but no tools
    if not tools:
        messages_without_tools, had_tool_content = strip_all_tool_content(messages)
        messages_with_assistants = messages_without_tools
        converted_tool_results = had_tool_content
    else:
        # Ensure assistant messages exist before tool_results (Kiro API requirement)
        # Also returns flag if any tool_results were converted (to skip thinking tag injection)
        messages_with_assistants, converted_tool_results = ensure_assistant_before_tool_results(messages)
    
    # Merge adjacent messages with the same role
    merged_messages = merge_adjacent_messages(messages_with_assistants)
    
    # Ensure first message is from user (Kiro API requirement, fixes issue #60)
    merged_messages = ensure_first_message_is_user(merged_messages)
    
    # Normalize unknown roles to 'user' (fixes issue #64)
    # This must happen BEFORE ensure_alternating_roles() so that consecutive
    # messages with unknown roles (e.g., 'developer') are properly detected
    merged_messages = normalize_message_roles(merged_messages)
    
    # Ensure alternating user/assistant roles (fixes issue #64)
    # Insert synthetic assistant messages between consecutive user messages
    merged_messages = ensure_alternating_roles(merged_messages)
    
    if not merged_messages:
        raise ValueError("No messages to send")
    
    # Build history (all messages except the last one)
    history_messages = merged_messages[:-1] if len(merged_messages) > 1 else []
    
    # If there's a system prompt, add it to the first user message in history
    if full_system_prompt and history_messages:
        first_msg = history_messages[0]
        if first_msg.role == "user":
            from dataclasses import replace as dc_replace
            original_content = extract_text_content(first_msg.content)
            history_messages = [
                dc_replace(first_msg, content=f"{full_system_prompt}\n\n{original_content}"),
                *history_messages[1:],
            ]
    
    history = build_kiro_history(history_messages, model_id)
    
    # Current message (the last one)
    current_message = merged_messages[-1]
    current_content = extract_text_content(current_message.content)
    
    # If system prompt exists but history is empty - add to current message
    if full_system_prompt and not history:
        current_content = f"{full_system_prompt}\n\n{current_content}"
    
    # If current message is assistant, need to add it to history
    # and create user message "Continue"
    if current_message.role == "assistant":
        history.append({
            "assistantResponseMessage": {
                "content": current_content
            }
        })
        current_content = "Continue"
    
    # If content is empty - use "Continue"
    if not current_content:
        current_content = "Continue"
    
    # Process images in current message - extract from message or content
    # IMPORTANT: images go directly into userInputMessage, NOT into userInputMessageContext
    # This matches the native Kiro IDE format
    images = current_message.images or extract_images_from_content(current_message.content)
    kiro_images = None
    if images:
        kiro_images = convert_images_to_kiro_format(images)
        if kiro_images:
            logger.debug(f"Added {len(kiro_images)} image(s) to current message")
    
    # Build user_input_context for tools and toolResults only (NOT images)
    user_input_context: Dict[str, Any] = {}
    
    # Add tools if present
    kiro_tools = convert_tools_to_kiro_format(processed_tools)
    if kiro_tools:
        user_input_context["tools"] = kiro_tools
    
    # Process tool_results in current message - convert to Kiro format if present
    if current_message.tool_results:
        # Convert unified format to Kiro format
        kiro_tool_results = convert_tool_results_to_kiro_format(current_message.tool_results)
        if kiro_tool_results:
            user_input_context["toolResults"] = kiro_tool_results
    else:
        # Try to extract from content (already in Kiro format)
        tool_results = extract_tool_results_from_content(current_message.content)
        if tool_results:
            user_input_context["toolResults"] = tool_results
    
    # Inject thinking tags if enabled (only for the current/last user message)
    if inject_thinking and current_message.role == "user":
        current_content = inject_thinking_tags(current_content)
    
    # Build userInputMessage
    user_input_message = {
        "content": current_content,
        "modelId": model_id,
        "origin": "AI_EDITOR",
    }
    
    # Add images directly to userInputMessage (NOT to userInputMessageContext)
    if kiro_images:
        user_input_message["images"] = kiro_images
    
    # Add user_input_context if present (contains tools and toolResults only)
    if user_input_context:
        user_input_message["userInputMessageContext"] = user_input_context
    
    # Assemble final payload
    payload = {
        "conversationState": {
            "chatTriggerType": "MANUAL",
            "conversationId": conversation_id,
            "currentMessage": {
                "userInputMessage": user_input_message
            }
        }
    }
    
    # Add history only if not empty
    if history:
        payload["conversationState"]["history"] = history
    
    # Add profileArn
    if profile_arn:
        payload["profileArn"] = profile_arn
    
    return KiroPayloadResult(payload=payload, tool_documentation=tool_documentation)
