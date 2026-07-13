class HeaderDetector:
    TARGET_FIELDS = {
        "背番号": ["背番号", "番号", "No", "NO", "No.", "背No"],
        "氏名": ["氏名", "名前", "選手名", "氏　名"],
        "ふりがな": ["ふりがな", "フリガナ", "ふり仮名", "よみがな"],

        "スタッフ分類": ["スタッフ分類", "区分", "種別", "役職", "役割"],
        "学年": ["学年", "学年区分"],
        "生年月日": ["生年月日", "誕生日", "生年月", "出生年月日"],
        "性別": ["性別", "男／女", "男女"],
        "出身地": ["出身地", "都道府県", "出身県", "出身都道府県", "県名"],
        "出身小中学校": ["出身小中学校", "小中学校", "出身中学校", "中学校", "出身校小中"],
        "高校": ["高校", "出身高校", "出身校", "高校名", "卒業高校"],
        "大学": ["大学", "大学名"],
        "身長cm": ["身長", "身長cm", "身長(cm)", "身長ＣＭ", "Height"],
        "体重kg": ["体重", "体重kg", "体重(kg)", "体重ＫＧ", "Weight"],
        "守備位置": ["守備位置", "位置", "ポジション", "守備"],
        "投": ["投", "投げ", "投手利き腕", "投打"],
        "打": ["打", "打ち", "打者利き腕", "投打"],
        "経歴": ["経歴", "球歴", "野球歴"],
    }

    def __init__(self, rows):
        self.rows = rows

    def normalize(self, value):
        if value is None:
            return ""

        text = str(value).strip()
        text = text.replace("　", "")
        text = text.replace(" ", "")
        text = text.replace("\n", "")
        text = text.replace("\r", "")
        return text

    def is_match(self, field_name, cell_text, keyword):
        key = self.normalize(keyword)

        if not cell_text or not key:
            return False

        # 誤判定しやすい項目は完全一致を優先
        exact_match_fields = {
            "学年",
            "出身地",
            "性別",
            "大学",
            "投",
            "打",
        }

        if field_name in exact_match_fields:
            return cell_text == key

        return cell_text == key or key in cell_text

    def detect(self):
        best_row_index = None
        best_score = 0
        best_columns = {}

        for row_index, row in enumerate(self.rows, start=1):
            columns = {}
            score = 0

            for col_index, value in enumerate(row, start=1):
                cell_text = self.normalize(value)

                if not cell_text:
                    continue

                for field_name, keywords in self.TARGET_FIELDS.items():
                    for keyword in keywords:
                        if self.is_match(field_name, cell_text, keyword):
                            if field_name not in columns:
                                columns[field_name] = col_index
                                score += 1

            if score > best_score:
                best_score = score
                best_row_index = row_index
                best_columns = columns

        return {
            "header_row": best_row_index,
            "score": best_score,
            "columns": best_columns
        }