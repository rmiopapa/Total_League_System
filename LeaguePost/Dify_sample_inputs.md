# Dify テスト用サンプル入力

## games_json

```json
[
  {
    "game_no": 1,
    "team1": "下市大",
    "team2": "鳥大医",
    "score": "鳥大医 4-1 下市大",
    "game_id": "20262158147",
    "date": "2026/03/26",
    "time": "14:00",
    "pitching_context": {
      "teams_from_schedule": ["下市大", "鳥大医"],
      "team1_from_schedule": "下市大",
      "team2_from_schedule": "鳥大医",
      "top_team": "下市大",
      "bottom_team": "鳥大医",
      "confirmed_pitchers": [
        {
          "name": "山端 結陽",
          "team": "鳥大医",
          "opponent": "下市大",
          "role": "先発投手",
          "do_not_assign_to": "下市大",
          "evidence": "1回表 下市大の攻撃 / 先発は: 山端 結陽"
        },
        {
          "name": "野上 凛太郎",
          "team": "下市大",
          "opponent": "鳥大医",
          "role": "先発投手",
          "do_not_assign_to": "鳥大医",
          "evidence": "1回裏 鳥大医の攻撃 / 先発は: 野上 凛太郎"
        },
        {
          "name": "中河 温之介",
          "team": "下市大",
          "opponent": "鳥大医",
          "role": "救援投手",
          "do_not_assign_to": "鳥大医",
          "evidence": "7回裏 鳥大医の攻撃 / 【投手交代】野上 凛太郎 → 中河 温之介"
        }
      ],
      "confirmed_pitchers_text": "山端 結陽 = 鳥大医（先発投手、相手: 下市大、下市大所属ではない）\n野上 凛太郎 = 下市大（先発投手、相手: 鳥大医、鳥大医所属ではない）\n中河 温之介 = 下市大（救援投手、相手: 鳥大医、鳥大医所属ではない）",
      "pitcher_evidence_by_team": [
        {
          "team": "下市大",
          "pitchers": [
            {"name": "野上 凛太郎", "team": "下市大", "opponent": "鳥大医", "role": "先発投手"},
            {"name": "中河 温之介", "team": "下市大", "opponent": "鳥大医", "role": "救援投手"}
          ],
          "pitcher_evidence": [
            "野上 凛太郎: 1回裏 鳥大医の攻撃 / 先発は: 野上 凛太郎",
            "中河 温之介: 7回裏 鳥大医の攻撃 / 【投手交代】野上 凛太郎 → 中河 温之介"
          ]
        },
        {
          "team": "鳥大医",
          "pitchers": [
            {"name": "山端 結陽", "team": "鳥大医", "opponent": "下市大", "role": "先発投手"}
          ],
          "pitcher_evidence": [
            "山端 結陽: 1回表 下市大の攻撃 / 先発は: 山端 結陽"
          ]
        }
      ]
    },
    "text_live": "2026/3/26 倉敷市営球場。下市大 1-4 鳥大医。1回表 下市大の攻撃、先発は山端結陽。1回裏 鳥大医の攻撃、先発は野上凛太郎。4回表、下市大は堀池真広の右適時打で1点を先制。6回裏、鳥大医は平野裕典の中適時打で逆転し、漆畑拓斗の左適時打などで4点を奪った。7回裏、下市大は野上凛太郎から中河温之介へ投手交代。鳥大医の山端結陽は9回を投げ切った。"
  }
]
```

## pitching_context_json

```json
{
  "teams_from_schedule": ["下市大", "鳥大医"],
  "team1_from_schedule": "下市大",
  "team2_from_schedule": "鳥大医",
  "top_team": "下市大",
  "bottom_team": "鳥大医",
  "confirmed_pitchers": [
    {
      "name": "山端 結陽",
      "team": "鳥大医",
      "opponent": "下市大",
      "role": "先発投手",
      "do_not_assign_to": "下市大",
      "evidence": "1回表 下市大の攻撃 / 先発は: 山端 結陽"
    },
    {
      "name": "野上 凛太郎",
      "team": "下市大",
      "opponent": "鳥大医",
      "role": "先発投手",
      "do_not_assign_to": "鳥大医",
      "evidence": "1回裏 鳥大医の攻撃 / 先発は: 野上 凛太郎"
    },
    {
      "name": "中河 温之介",
      "team": "下市大",
      "opponent": "鳥大医",
      "role": "救援投手",
      "do_not_assign_to": "鳥大医",
      "evidence": "7回裏 鳥大医の攻撃 / 【投手交代】野上 凛太郎 → 中河 温之介"
    }
  ],
  "confirmed_pitchers_text": "山端 結陽 = 鳥大医（先発投手、相手: 下市大、下市大所属ではない）\n野上 凛太郎 = 下市大（先発投手、相手: 鳥大医、鳥大医所属ではない）\n中河 温之介 = 下市大（救援投手、相手: 鳥大医、鳥大医所属ではない）"
}
```

## confirmed_pitchers_json

```json
[
  {
    "name": "山端 結陽",
    "team": "鳥大医",
    "opponent": "下市大",
    "role": "先発投手",
    "do_not_assign_to": "下市大",
    "evidence": "1回表 下市大の攻撃 / 先発は: 山端 結陽"
  },
  {
    "name": "野上 凛太郎",
    "team": "下市大",
    "opponent": "鳥大医",
    "role": "先発投手",
    "do_not_assign_to": "鳥大医",
    "evidence": "1回裏 鳥大医の攻撃 / 先発は: 野上 凛太郎"
  },
  {
    "name": "中河 温之介",
    "team": "下市大",
    "opponent": "鳥大医",
    "role": "救援投手",
    "do_not_assign_to": "鳥大医",
    "evidence": "7回裏 鳥大医の攻撃 / 【投手交代】野上 凛太郎 → 中河 温之介"
  }
]
```

## pitcher_usage_instruction

```text
confirmed_pitchers_json を投手所属の絶対根拠としてください。
confirmed_pitchers_json の name は必ず team 所属です。
do_not_assign_to のチーム所属として書いてはいけません。
text_live の並びや「A vs B」の表記より confirmed_pitchers_json を優先してください。
confirmed_pitchers_json に含まれる投手名は、積極的に寸評に入れてください。
```
