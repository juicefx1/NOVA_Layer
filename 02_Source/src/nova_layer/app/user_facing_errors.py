from __future__ import annotations

"""Map application / plugin error codes to recovery-oriented user text.

Keeps the existing `CODE: message` emit contract while improving dialog copy.
"""

_RETRY_HINTS: dict[str, str] = {
    "OUT_OF_MEMORY": "Retry with a smaller image, or switch to a CPU provider.",
    "CANCELLED": "The operation was cancelled. You can start it again when ready.",
    "BATCH_CANCELLED": "Batch was cancelled. Use Retry Cancelled to resume remaining items.",
    "MODEL_NOT_AVAILABLE": "Install the model checkpoint or select another provider, then retry.",
    "MODEL_LOAD_FAILED": "Check the model path and try again.",
    "INFERENCE_FAILED": "Adjust guidance and retry generation.",
    "EXTRACTION_FAILED": "Confirm a hypothesis first, then retry extraction.",
    "IMAGE_DECODE_FAILED": "Open a supported PNG or JPEG and try again.",
    "PLUGIN_PACKAGE_SYMLINK_FORBIDDEN": (
        "Rebuild the package without symbolic links, then reinstall."
    ),
    "PLUGIN_PACKAGE_UNSAFE_PATH": (
        "Rebuild the package with safe relative paths, then reinstall."
    ),
    "PLUGIN_PACKAGE_CORRUPT": (
        "Re-download or rebuild the .nova-plugin package, then retry install."
    ),
    "PLUGIN_PACKAGE_CHECKSUM_INVALID": "Verify the package checksum and reinstall.",
    "PATH_TRAVERSAL": "Choose a destination inside an allowed folder and retry.",
    "DESTINATION_EXISTS": "Choose a new filename or enable overwrite, then retry.",
    "BATCH_ENGINE_REPLACED": "Restart the batch after provider changes settle.",
    "NO_BATCH_JOB": "Create a batch queue before starting.",
    "BATCH_IN_PROGRESS": "Wait for the current batch to finish, or cancel it first.",
    "UNSUPPORTED_PROVIDER_CAPABILITY": (
        "Change guidance signals or select a compatible provider."
    ),
    "GENERATION_NOT_CONFIRMABLE": "Select a candidate and confirm before continuing.",
    "ASSET_NOT_FOUND": "Reload the project or source image, then retry.",
    "EXPORT_FAILED": "Check disk permissions and free space, then retry export.",
}


def format_user_error(raw: str) -> str:
    """Turn `CODE: detail` (or plain text) into a clearer dialog message."""
    code = ""
    detail = raw.strip()
    if ": " in raw:
        maybe_code, rest = raw.split(": ", 1)
        looks_like_code = (
            maybe_code
            and maybe_code.replace("_", "").isalnum()
            and maybe_code.upper() == maybe_code
        )
        if looks_like_code:
            code = maybe_code
            detail = rest.strip()
    if not code:
        return detail
    hint = _RETRY_HINTS.get(code)
    title = code.replace("_", " ").title()
    lines = [f"{title}.", detail]
    if hint:
        lines.append(hint)
    return "\n\n".join(lines)


def cancellation_status(kind: str = "operation") -> str:
    if kind == "batch":
        return "Batch cancellation requested — finishing the current item safely…"
    return "Cancellation requested — waiting for the operation to stop…"
