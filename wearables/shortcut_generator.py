"""
shortcut_generator.py
Generates iOS Shortcuts (.shortcut plist) for the Arnie Health sync workflow.

Plist format derived from a real working iCloud shortcut (Energy Balance by
Katie Reagan Patton — https://www.icloud.com/shortcuts/cc22c46649d3428bbf181f1ea7f623b4).
Key findings vs. earlier attempts:
  - Action identifier: is.workflow.actions.filter.health.quantity  ✓
  - Health type is the UI display name ("Step Count", not HKQuantityTypeIdentifier)
  - WFContentItemFilter uses WFActionParameterFilterTemplates (array of conditions)
  - Aggregation: WFHKSampleFilteringGroupBy = "Day"  (NOT WFHealthQuantityAggregationStyle)
  - WFHKSampleFilteringFillMissing = false
  - Set Variable must include WFInput → OutputUUID → linking to the health action's UUID
"""
from __future__ import annotations
import plistlib
import uuid as _uuid_mod

# Unicode OBJECT REPLACEMENT CHARACTER — placeholder inside WFWorkflowVariableString.
_PH = "￼"


# ── Low-level helpers ──────────────────────────────────────────────────────────

def _new_uuid() -> str:
    return str(_uuid_mod.uuid4()).upper()


def _named_var(name: str) -> dict:
    """Attachment referencing a named Shortcuts variable."""
    return {"Aggrandizements": [], "Type": "Variable", "VariableName": name}


def _var_string(template: str, positions: dict) -> dict:
    """Build a WFWorkflowVariableString value dict."""
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

def _health_action(display_name: str, action_uuid: str, output_name: str) -> dict:
    """
    Find Health Samples — filters to the last 1 day and groups by Day.
    Grouping by Day produces a single aggregated value for today.

    display_name must be the Shortcuts UI name (e.g. "Step Count", "Active Calories").
    action_uuid is used so the subsequent Set Variable can reference this action.
    """
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.filter.health.quantity",
        "WFWorkflowActionParameters": {
            "UUID": action_uuid,
            "CustomOutputName": output_name,
            "WFContentItemFilter": {
                "WFSerializationType": "WFContentPredicateTableTemplate",
                "Value": {
                    "WFActionParameterFilterPrefix": 1,
                    "WFContentPredicateBoundedDate": False,
                    "WFActionParameterFilterTemplates": [
                        # Condition 1: Type == display_name
                        {
                            "Bounded": True,
                            "Operator": 4,          # equals
                            "Property": "Type",
                            "Removable": False,
                            "Values": {
                                "Enumeration": {
                                    "Value": display_name,
                                    "WFSerializationType": "WFStringSubstitutableState",
                                },
                            },
                        },
                        # Condition 2: Start Date is within the last 1 day
                        {
                            "Bounded": True,
                            "Operator": 1002,       # is within last N units
                            "Property": "Start Date",
                            "Removable": False,
                            "Values": {
                                "Number": {
                                    "Value": "1",
                                    "WFSerializationType": "WFNumberStringSubstitutableState",
                                },
                                "Unit": {
                                    "Value": 16,    # NSCalendarUnitDay
                                    "WFSerializationType": "WFCalendarUnitSubstitutableState",
                                },
                            },
                        },
                    ],
                },
            },
            "WFContentItemLimitEnabled": False,
            "WFContentItemLimitNumber": 1.0,
            "WFContentItemSortOrder": "Oldest First",
            "WFContentItemSortProperty": "Start Date",
            "WFHKSampleFilteringFillMissing": False,
            "WFHKSampleFilteringGroupBy": "Day",   # ← aggregates into one value per day
        },
    }


def _set_variable_from_action(var_name: str, action_uuid: str,
                               output_display: str = "Health Samples") -> dict:
    """
    Set Variable — explicitly links to action_uuid's output.
    output_display is the label Shortcuts shows for the action's output token.
    """
    return {
        "WFWorkflowActionIdentifier": "is.workflow.actions.setvariable",
        "WFWorkflowActionParameters": {
            "WFInput": {
                "WFSerializationType": "WFTextTokenAttachment",
                "Value": {
                    "Type": "ActionOutput",
                    "OutputName": output_display,
                    "OutputUUID": action_uuid,
                },
            },
            "WFVariableName": var_name,
        },
    }


def _url_action_with_endpoint_var() -> dict:
    """URL action — endpoint_url variable + 4 health metric variables."""
    seg1 = "&steps="            # 7
    seg2 = "&active_calories="  # 17
    seg3 = "&resting_calories=" # 18
    seg4 = "&sleep_seconds="    # 15

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


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_arnie_shortcut_template() -> bytes:
    """
    Unsigned template shortcut with an import question for the sync URL.

    Sign once on macOS before distributing:
        shortcuts sign --mode anyone \\
          --input arnie_unsigned.shortcut \\
          --output wearables/arnie_health.shortcut

    When imported, iOS asks "Your Arnie sync URL" — user pastes the URL
    shown (with a Copy button) on the guide page.
    """
    text_uuid   = _new_uuid()
    steps_uuid  = _new_uuid()
    cals_uuid   = _new_uuid()
    rest_uuid   = _new_uuid()
    sleep_uuid  = _new_uuid()

    text_action = {
        "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {
            "UUID": text_uuid,
            "WFTextActionText": "",
            "CustomOutputName": "Endpoint URL",
        },
    }

    actions = [
        # 0: Text placeholder (import question fills this with the sync URL)
        text_action,
        # 1: Save it as named variable
        _set_variable_from_action("endpoint_url", text_uuid, output_display="Text"),

        # Health queries — each followed by a Set Variable
        _health_action("Step Count",        steps_uuid, "Steps"),
        _set_variable_from_action("steps", steps_uuid),

        _health_action("Active Calories",   cals_uuid, "Active Calories"),
        _set_variable_from_action("cals",  cals_uuid),

        _health_action("Resting Calories",  rest_uuid, "Resting Calories"),
        _set_variable_from_action("rest",  rest_uuid),

        _health_action("Time Asleep",       sleep_uuid, "Sleep"),
        _set_variable_from_action("sleep", sleep_uuid),

        # Build + fire the URL
        _url_action_with_endpoint_var(),
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {},
        },
    ]

    shortcut = {
        "WFQuickActionSurfaces": [],
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
    return plistlib.dumps(shortcut, fmt=plistlib.FMT_XML)


def generate_arnie_shortcut(endpoint_url: str) -> bytes:
    """Embedded-token version — for local testing only, not distributable."""
    steps_uuid = _new_uuid()
    cals_uuid  = _new_uuid()
    rest_uuid  = _new_uuid()
    sleep_uuid = _new_uuid()

    seg0 = endpoint_url + "&steps="
    seg1 = "&active_calories="
    seg2 = "&resting_calories="
    seg3 = "&sleep_seconds="
    template = seg0 + _PH + seg1 + _PH + seg2 + _PH + seg3 + _PH
    pos_steps = len(seg0)
    pos_cals  = pos_steps + 1 + len(seg1)
    pos_rest  = pos_cals  + 1 + len(seg2)
    pos_sleep = pos_rest  + 1 + len(seg3)

    url_action = {
        "WFWorkflowActionIdentifier": "is.workflow.actions.url",
        "WFWorkflowActionParameters": {
            "WFURLActionURL": _var_string(
                template,
                {pos_steps: "steps", pos_cals: "cals",
                 pos_rest: "rest",   pos_sleep: "sleep"},
            )
        },
    }

    shortcut = {
        "WFQuickActionSurfaces": [],
        "WFWorkflowActions": [
            _health_action("Step Count",       steps_uuid, "Steps"),
            _set_variable_from_action("steps", steps_uuid),
            _health_action("Active Calories",  cals_uuid, "Active Calories"),
            _set_variable_from_action("cals",  cals_uuid),
            _health_action("Resting Calories", rest_uuid, "Resting Calories"),
            _set_variable_from_action("rest",  rest_uuid),
            _health_action("Time Asleep",      sleep_uuid, "Sleep"),
            _set_variable_from_action("sleep", sleep_uuid),
            url_action,
            {"WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
             "WFWorkflowActionParameters": {}},
        ],
        "WFWorkflowImportQuestions": [],
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
    return plistlib.dumps(shortcut, fmt=plistlib.FMT_XML)
