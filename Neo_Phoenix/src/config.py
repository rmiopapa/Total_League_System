"""Phoenix V3.0 runtime feature flags.

Sprint04 keeps the Rule 9.16(e) switch point and makes RunDetail the summary master.
Default is False to preserve V2.6 / GoldData102 behavior.
"""

# When False, earned-run comparison uses the existing Team Virtual report.
# When True, the comparator can be given a Pitcher Virtual report/timeline.
USE_PITCHER_VIRTUAL = False

# Sprint04: TeamPitcherSummary must be generated from RunDetail only.
RUNDETAIL_IS_SUMMARY_MASTER = True


# Phoenix V3.1 Regression Gate
# スコア不正（進塁理由未記入等）のため、Team GoldData から除外するRC。
# RC063 is excluded because the source速報 text is incomplete:
# the scorebook shows a double steal where the runner on third scored and
# the runner on second was put out, but that play is missing from sample.txt.
GOLDDATA_EXCLUDED_CASES = {"RC063"}

# Neo-only judgment validation holds cases where GoldData is under review.
# This does not affect Phoenix StableGate.
NEO_JUDGMENT_EXCLUDED_CASES = {"RC067", "RC112", "RC221"}

# PitcherGoldData は固定リストではなく、regression_cases/RC***/pitcher_expected.json を持つ全RCを検証する。
PITCHER_GOLDDATA_CASES = []
