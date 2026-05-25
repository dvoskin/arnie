# Skill: Travel Damage Control

## Purpose
Help a user maintain progress (or minimise damage) while travelling when
food choices and training access are limited.

## Trigger
- User mentions: "travelling", "on the road", "airport", "hotel",
  "stuck on a layover", "business trip", "no gym access"

## Logic
1. Identify constraints from context (no kitchen, airport, hotel gym only, etc.)
2. Prioritise protein first — it's the hardest macro to hit while travelling
3. Give practical, portable food options for the specific situation
4. Suggest training modifications (hotel room workout, walking, etc.)
5. Set realistic expectations — maintenance or slight deficit is a win

## Response Format
```
Travel mode — [situation].

Food priorities:
• [option 1 — widely available]
• [option 2]
• [option 3]

Training: [practical alternative given constraints]

Target: [adjusted realistic macro goal for the day]
```

## Rules
- Be practical — no suggestions requiring cooking unless user has a kitchen
- Alcohol management: acknowledge it if relevant, give honest advice
- Aim for 80–90% of normal targets, not perfection
- Specific to the travel context (airport ≠ hotel ≠ road trip)

## Example Output
```
Airport day — eat before you board if possible.

Food picks:
• Grilled chicken sandwich, no sauce — any airport café
• Greek yoghurt parfait (skip the granola) — Starbucks
• Almonds + beef jerky — duty free snacks
• Water, not juice

Training: walk between gates. Hit 10k steps. That's your cardio.

Target: 150g protein, stay under maintenance. Skip the airport beer.
```
