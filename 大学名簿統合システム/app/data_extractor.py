from app.normalizer import Normalizer
from app.staff_classifier import StaffClassifier


class DataExtractor:
    def __init__(self, rows, header_info):
        self.rows = rows
        self.header_row = header_info.get("header_row")
        self.columns = header_info.get("columns", {})

    def clean(self, value):
        return Normalizer.clean_text(value)

    def get_value(self, row, field_name):
        col_index = self.columns.get(field_name)

        if not col_index:
            return ""

        zero_index = col_index - 1

        if zero_index < 0 or zero_index >= len(row):
            return ""

        return self.clean(row[zero_index])

    def is_probably_data_row(self, row):
        no = self.get_value(row, "背番号")
        name = self.get_value(row, "氏名")
        grade = self.get_value(row, "学年")
        position = self.get_value(row, "守備位置")
        staff = self.get_value(row, "スタッフ分類")

        if name and name not in ["氏名", "名前", "選手名"]:
            return True

        if no and position:
            return True

        if no and grade:
            return True

        if name and staff:
            return True

        return False

    def extract(self, limit=None):
        results = []

        if not self.header_row:
            return results

        start_index = self.header_row

        for row in self.rows[start_index:]:
            if not self.is_probably_data_row(row):
                continue

            raw_name = self.get_value(row, "氏名")
            normalized_name = Normalizer.normalize_name(raw_name)
            short_name = Normalizer.create_short_name(raw_name)

            raw_position = self.get_value(row, "守備位置")
            raw_staff = self.get_value(row, "スタッフ分類")

            # スタッフ分類列があれば優先、なければ守備位置・役職列から判定
            if raw_staff:
                staff_type = StaffClassifier.classify(raw_staff)
            else:
                staff_type = StaffClassifier.classify(raw_position)

            raw_throw = self.get_value(row, "投")
            raw_bat = self.get_value(row, "打")

            if raw_throw and raw_throw == raw_bat:
                throw_value, bat_value = Normalizer.split_throw_bat(raw_throw)
            else:
                throw_value = raw_throw
                bat_value = raw_bat

            item = {
                "背番号": Normalizer.normalize_back_number(self.get_value(row, "背番号")),
                "氏名": normalized_name,
                "略名": short_name,
                "ふりがな": self.get_value(row, "ふりがな"),

                "スタッフ分類": staff_type,
                "学年": Normalizer.normalize_grade(self.get_value(row, "学年")),
                "生年月日": self.get_value(row, "生年月日"),
                "性別": self.get_value(row, "性別"),
                "出身地": self.get_value(row, "出身地"),
                "出身小中学校": self.get_value(row, "出身小中学校"),

                "高校": self.get_value(row, "高校"),
                "大学": self.get_value(row, "大学"),
                "身長cm": Normalizer.normalize_height(self.get_value(row, "身長cm")),
                "体重kg": Normalizer.normalize_weight(self.get_value(row, "体重kg")),
                "守備位置": raw_position,
                "投": throw_value,
                "打": bat_value,
                "経歴": self.get_value(row, "経歴"),
            }

            results.append(item)

            if limit is not None and len(results) >= limit:
                break

        same_mark_fields = [
            "高校",
            "学年",
            "出身地",
            "出身小中学校",
            "守備位置",
            "投",
            "打",
            "スタッフ分類",
        ]

        results = Normalizer.fill_same_marks(results, same_mark_fields)

        return results