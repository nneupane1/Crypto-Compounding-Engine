from __future__ import annotations

from pathlib import Path

from structural_compounding_lab.common.project_paths import package_root


def smtp_allowed_for_output_root(output_root: Path) -> tuple[bool, str]:
    """Allow real SMTP only for artifacts under the active project output root.

    Tests and diagnostics often use temporary folders. Those folders may write
    local email drafts, but they must not send real email because a temp artifact
    root can make the operator believe the live scheduler produced the message.
    """

    try:
        resolved_output = output_root.resolve()
        allowed_root = (package_root() / "output").resolve()
    except Exception:
        return False, "smtp_blocked_unresolvable_output_root"
    if resolved_output == allowed_root or allowed_root in resolved_output.parents:
        return True, "smtp_allowed_project_output_root"
    return False, f"smtp_blocked_non_project_output_root:{resolved_output}"
