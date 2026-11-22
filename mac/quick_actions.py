"""Write ~/Library/Services/Ask Opto*.workflow (Automator Quick Actions).

    python3 mac/quick_actions.py /path/to/mac/ask-opto.sh
"""

import plistlib
import sys
import uuid
from pathlib import Path


def build(script: str, name: str, input_type: str, send: dict, input_method: int) -> None:
    root = Path.home() / "Library/Services" / f"{name}.workflow" / "Contents"
    root.mkdir(parents=True, exist_ok=True)
    with (root / "Info.plist").open("wb") as f:
        plistlib.dump({"NSServices": [{"NSMenuItem": {"default": name},
                                       "NSMessage": "runWorkflowAsService", **send}]}, f)
    uid = lambda: str(uuid.uuid4()).upper()  # noqa: E731
    action = {
        "AMAccepts": {"Container": "List", "Optional": True, "Types": ["com.apple.cocoa.string"]},
        "AMActionVersion": "2.0.3", "AMApplication": ["Automator"],
        "AMParameterProperties": {k: {} for k in ("COMMAND_STRING", "CheckedForUserDefaultShell",
                                                  "inputMethod", "shell", "source")},
        "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
        "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
        "ActionName": "Run Shell Script",
        "ActionParameters": {"COMMAND_STRING": f'"{script}" "$@"', "CheckedForUserDefaultShell": True,
                             "inputMethod": input_method, "shell": "/bin/bash", "source": ""},
        "BundleIdentifier": "com.apple.RunShellScript", "CFBundleVersion": "2.0.3",
        "CanShowSelectedItemsWhenRun": False, "CanShowWhenRun": True,
        "Category": ["AMCategoryUtilities"], "Class Name": "RunShellScriptAction",
        "InputUUID": uid(), "Keywords": ["Shell", "Script"], "OutputUUID": uid(), "UUID": uid(),
        "UnlocalizedApplications": ["Automator"], "arguments": {}, "isViewVisible": 1,
    }
    with (root / "document.wflow").open("wb") as f:
        plistlib.dump({
            "AMApplicationBuild": "523", "AMApplicationVersion": "2.10", "AMDocumentVersion": "2",
            "actions": [{"action": action, "isViewVisible": 1}], "connectors": {},
            "workflowMetaData": {"serviceInputTypeIdentifier": input_type,
                                 "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
                                 "serviceProcessesInput": 0,
                                 "workflowTypeIdentifier": "com.apple.Automator.servicesMenu"},
        }, f)


if __name__ == "__main__":
    script = sys.argv[1]
    build(script, "Ask Opto", "com.apple.Automator.text", {"NSSendTypes": ["public.utf8-plain-text"]}, 0)
    build(script, "Ask Opto (Image)", "com.apple.Automator.fileSystemObject.image",
          {"NSSendFileTypes": ["public.image"],
           "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"}}, 1)
