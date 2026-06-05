"""
shortcut_generator.py
Generates iOS Shortcuts (.shortcut plist) for the Arnie Health sync workflow.

Two modes:
  generate_arnie_shortcut_template()
      Returns an UNSIGNED template with an import question.
      Sign once on macOS with:
        shortcuts sign --mode anybody \
          --input arnie_unsigned.shortcut \
          --output wearables/arnie_health.shortcut
      The same signed file works for ALL users — they paste their URL on import.

  generate_arnie_shortcut(endpoint_url)
      Returns an unsigned shortcut with the token already embedded.
      Kept for local testing / debugging only.
"""
from __future__ import annotations
import plistlib

# Unicode OBJECT REPLACEMENT CHARACTER — iOS Shortcuts uses this as the
# single-character stand-in for each variable inside WFWorkflowVariableString.
_PH = "￼"


# ── Low-level helpers ──────────────────────────────────────────────────────────

def _named_var(name: str) -> dict:
    """Attachment dict referencing a named Shortcuts variable."""
    return {"Aggrandizements": [], "Type": "Variable", "VariableName": name}


def _var_string(template: str, positions: dict) -> dict:
    """
    Build a WFWorkflowVariableString value dict.

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


# ── Action builders ────────────────────────────────────────────────────────────

def _health_action(hk_type: str, output_name: str) -> dict:
    """Find Health Samples — queries one metric for today, aggregated as Sum."""
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
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.setvariable",
        "WFWorkflowActionParameters": {"WFVariableName": name},
    }


def _url_action_with_endpoint_var() -> dict:
    """
    URL action where the base endpoint is the 'endpoint_url' named variable.
    Template: [endpoint_url]&steps=[steps]&active_calories=[cals]...
    """
    seg1 = "&steps="            # 7 chars
    seg2 = "&active_calories="  # 17 chars
    seg3 = "&resting_calories=" # 18 chars
    seg4 = "&sleep_seconds="    # 15 chars

    template = _PH + seg1 + _PH + seg2 + _PH + seg3 + _PH + seg4 + _PH

    pos_endpoint = 0
    pos_steps    = pos_endpoint + 1 + len(seg1)   # 8
    pos_cals     = pos_steps    + 1 + len(seg2)   # 26
    pos_rest     = pos_cals     + 1 + len(seg3)   # 45
    pos_sleep    = pos_rest     + 1 + len(seg4)   # 61

    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.url",
        "WFWorkflowActionParameters": {
            "WFURLActionURL": _var_string(
                template,
                {
                    pos_endpoint: "endpoint_url",
                    pos_steps:    "steps",
                    pos_cals:     "cals",
                    pos_rest:     "rest",
                    pos_sleep:    "sleep",
                },
            )
        },
    }


def _url_action_embedded(endpoint_url: str) -> dict:
    """URL action with the endpoint URL embedded as a literal string."""
    seg0 = endpoint_url + "&steps="
    seg1 = "&active_calories="
    seg2 = "&resting_calories="
    seg3 = "&sleep_seconds="

    template = seg0 + _PH + seg1 + _PH + seg2 + _PH + seg3 + _PH

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


# ── Shared shortcut metadata ───────────────────────────────────────────────────

_BASE_META = {
    "WFWorkflowClientVersion": "1209.0.0.0.0",
    "WFWorkflowHasOutputFallback": False,
    "WFWorkflowInputContentItemClasses": [],
    "WFWorkflowMinimumClientVersion": 900,
    "WFWorkflowMinimumClientVersionString": "900",
    "WFWorkflowOutputContentItemClasses": [],
    "WFWorkflowTypes": [],
    "WFWorkflowIcon": {
        "WFWorkflowIconGlyphNumber": 59511,
        "WFWorkflowIconStartColor": 431817727,
    },
}

_HEALTH_ACTIONS = [
    _health_action("HKQuantityTypeIdentifierStepCount",         "Steps"),
    _set_variable("steps"),
    _health_action("HKQuantityTypeIdentifierActiveEnergyBurned","Active Calories"),
    _set_variable("cals"),
    _health_action("HKQuantityTypeIdentifierBasalEnergyBurned", "Resting Calories"),
    _set_variable("rest"),
    _health_action("HKCategoryTypeIdentifierSleepAnalysis",     "Sleep"),
    _set_variable("sleep"),
]

_GET_CONTENTS = {
    "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
    "WFWorkflowActionParameters": {},
}


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_arnie_shortcut_template() -> bytes:
    """
    Unsigned template shortcut with an import question for the sync URL.

    Sign the output once on macOS before distributing:
        shortcuts sign --mode anybody \\
          --input arnie_unsigned.shortcut \\
          --output wearables/arnie_health.shortcut

    The signed file is token-agnostic — every user pastes their own URL
    (shown with a Copy button on the guide page) when iOS prompts them.

    Action layout (0-based indices, referenced by WFWorkflowImportQuestions):
      0  Text (placeholder for endpoint URL)   ← import question fills this
      1  Set Variable "endpoint_url"
      2  Find Health Samples – Steps
      3  Set Variable "steps"
      4  Find Health Samples – Active Energy
      5  Set Variable "cals"
      6  Find Health Samples – Basal Energy
      7  Set Variable "rest"
      8  Find Health Samples – Sleep
      9  Set Variable "sleep"
      10 URL  ([endpoint_url]&steps=[steps]…)
      11 Get Contents of URL
    """
    text_action = {
        "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {
            "WFTextActionText": "",
            "CustomOutputName": "Endpoint URL",
        },
    }

    actions = (
        [text_action, _set_variable("endpoint_url")]
        + _HEALTH_ACTIONS
        + [_url_action_with_endpoint_var(), _GET_CONTENTS]
    )

    shortcut = {
        **_BASE_META,
        "WFWorkflowActions": actions,
        "WFWorkflowImportQuestions": [
            {
                "ActionIndex": 0,
                "Category": "Parameter",
                "ParameterKey": "WFTextActionText",
                "DefaultValue": "",
                "Text": "Your Arnie sync URL",
            }
        ],
    }
    return plistlib.dumps(shortcut, fmt=plistlib.FMT_XML)


def generate_arnie_shortcut(endpoint_url: str) -> bytes:
    """
    Unsigned shortcut with the endpoint URL (including token) embedded.
    For local testing/debugging — not distributable without signing.
    """
    actions = _HEALTH_ACTIONS + [_url_action_embedded(endpoint_url), _GET_CONTENTS]
    shortcut = {
        **_BASE_META,
        "WFWorkflowActions": actions,
        "WFWorkflowImportQuestions": [],
    }
    return plistlib.dumps(shortcut, fmt=plistlib.FMT_XML)
