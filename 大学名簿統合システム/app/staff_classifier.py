class StaffClassifier:
    PLAYER_POSITIONS = {
        "投手",
        "捕手",
        "内野手",
        "外野手",
        "投",
        "捕",
        "内",
        "外",
    }

    SCOREKEEPER_WORDS = {
        "スコアラー",
        "記録員",
        "記録",
    }

    @staticmethod
    def classify(value):
        if value is None:
            return ""

        text = str(value).strip()

        if not text:
            return ""

        normalized = text.replace("　", "").replace(" ", "")

        if normalized in StaffClassifier.PLAYER_POSITIONS:
            return "選手"

        if normalized in StaffClassifier.SCOREKEEPER_WORDS:
            return "記録員"

        return text