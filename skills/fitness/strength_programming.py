TRIGGERS = ["what's my 1RM", "write me a program", "I'm stalling on", "training split", "show my PRs", "what should I run"]

PROMPT = """\
Use [ESTIMATED 1RMs] from context — computed from logged sets, not fabricated.
1RM format: "[Lift] est. 1RM: ~Xlb / Xkg (from Wlb x Rreps)\n  85%: Xlb x 3-5  |  75%: Xlb x 6-8  |  65%: Xlb x 12\n[1 coaching note]"
Program recommendations: beginner → linear progression (+5lb upper/+10lb lower per session); intermediate → 5/3/1 or PPL; advanced → periodised blocks.
Stall = same weight/reps 3 sessions in a row. Solutions: add volume, check recovery, change rep range.
Deload: reduce sets 40-50%, keep weight. Every 4-6 weeks or when performance drops.
Always cross-reference [COACHING STATE] before programming — don't prescribe heavy loading on reduced/recovery days.\
"""
