"""
shortcut_generator.py
Generates a binary .shortcut plist (iOS Shortcuts) for the Arnie Health sync workflow.

The generated shortcut:
  1. Queries 4 Apple Health metrics (steps, active cals, resting cals, sleep)
  2. Saves each as a named Shortcuts variable
  3. Builds a GET URL with all values substituted
  4. Fires the request to sync data to Arnie

The plist is XML format so it's human-readable and easy to debug if any
action parameter key names change across iOS versions.
"""
from __future__ import annotations
import plistlib

# Unicode OBJECT REPLACEMENT CHARACTER — iOS Shortcuts uses this as the
# single-character stand-in for each variable inside WFWorkflowVariableString.
_PH = "￼"


# ── Low-level helpers ──────────────────────────────────────────────────────────

def _named_var(name: str) -> dict:
    """Attachment dict that references a named Shortcuts variable by name."""
    return {"Aggrandizements": [], "Type": "Variable", "VariableName": name}


def _var_string(template: str, positions: dict) -> dict:
    """
    Build a WFWorkflowVariableString dict.

    template  — string with _PH at each variable injection point
    positions — {char_offset: variable_name}
    """
    return {
        "WFSerializationType": "WFWorkflowVariableString",
        "Value": {
            "string": template,
            "attachmentsByRange": {
                f"{{{pos}, 1}}": _named_var(name)
                for pos, name in positions.items()
            },
        },
    }


# ── Shortcut action builders ───────────────────────────────────────────────────

def _health_action(hk_type: str, output_name: str) -> dict:
    """
    Find Health Samples — queries one metric for today, aggregated as Sum.
    Quantity types (steps, energy) use WFHealthQuantityTypeKey.
    Category types (sleep) use WFHealthCategoryKey.
    """
    is_category = hk_type.startswith("HKCategoryTypeIdentifier")
    params: dict = {
        "WFHealthReadingDateMode": "Today",
        "WFHealthQuantityAggregationStyle": 1,  # Sum
        "CustomOutputName": output_name,
    }
    if is_category:
        params["WFHealthCategoryKey"] = hk_type
    else:
        params["WFHealthQuantityTypeKey"] = hk_type
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.gethealth",
        "WFWorkflowActionParameters": params,
    }


def _set_variable(name: str) -> dict:
    """Saves the previous action's output to a named Shortcuts variable."""
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.setvariable",
        "WFWorkflowActionParameters": {"WFVariableName": name},
    }


def _url_action(endpoint_url: str) -> dict:
    """
    URL action with four named variables interpolated into the query string.
    Computes character offsets for each _PH placeholder.
    """
    seg0 = endpoint_url + "&steps="
    seg1 = "&active_calories="
    seg2 = "&resting_calories="
    seg3 = "&sleep_seconds="

    template = (
        seg0 + _PH
        + seg1 + _PH
        + seg2 + _PH
        + seg3 + _PH
    )

    pos_steps = len(seg0)
    pos_cals  = pos_steps + 1 + len(seg1)
    pos_rest  = pos_cals  + 1 + len(seg2)
    pos_sleep = pos_rest  + 1 + len(seg3)

    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.url",
        "WFWorkflowActionParameters": {
            "WFURLActionURL": _var_string(
                template,
                {
                    pos_steps: "steps",
                    pos_cals:  "cals",
                    pos_rest:  "rest",
                    pos_sleep: "sleep",
                },
            )
        },
    }


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_arnie_shortcut(endpoint_url: str) -> bytes:
    """
    Return an XML-plist .shortcut file for the Arnie Health sync shortcut.

    endpoint_url must already contain the user's token, e.g.:
        https://arnie.onrender.com/health/apple?token=abc123
    """
    shortcut = {
        "WFWorkflowActions": [
            _health_action("HKQuantityTypeIdentifierStepCount",        "Steps"),
            _set_variable("steps"),
            _health_action("HKQuantityTypeIdentifierActiveEnergyBurned", "Active Calories"),
            _set_variable("cals"),
            _health_action("HKQuantityTypeIdentifierBasalEnergyBurned",  "Resting Calories"),
            _set_variable("rest"),
            _health_action("HKCategoryTypeIdentifierSleepAnalysis",      "Sleep"),
            _set_variable("sleep"),
            _url_action(endpoint_url),
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
                "WFWorkflowActionParameters": {},
            },
        ],
        # Metadata
        "WFWorkflowClientVersion": "1209.0.0.0.0",
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowImportQuestions": [],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowTypes": [],
        # Icon — green lightning bolt
        "WFWorkflowIcon": {
            "WFWorkflowIconGlyphNumber": 59511,
            "WFWorkflowIconStartColor": 431817727,
        },
    }

    return plistlib.dumps(shortcut, fmt=plistlib.FMT_XML)
