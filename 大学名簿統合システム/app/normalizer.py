import re


class Normalizer:
    SAME_MARKS = {"〃", "々", "同上", '"', "”", "“", "＂", "'", "’", "‘"}

    @staticmethod
    def clean_text(value):
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def is_same_mark(value):
        text = Normalizer.clean_text(value)
        return text in Normalizer.SAME_MARKS

    @staticmethod
    def normalize_name(value):
        name = Normalizer.clean_text(value)

        if not name:
            return ""

        temp = name.replace("　", " ")
        temp = re.sub(r"\s+", " ", temp).strip()

        space_count = temp.count(" ")

        if space_count == 1:
            family, given = temp.split(" ", 1)
            return family + "　" + given

        if space_count >= 2:
            return temp.replace(" ", "")

        return temp

    @staticmethod
    def create_short_name(name):
        normalized = Normalizer.normalize_name(name)

        if "　" in normalized:
            return normalized.split("　", 1)[0]

        if " " in normalized:
            return normalized.split(" ", 1)[0]

        return normalized

    @staticmethod
    def split_throw_bat(value):
        text = Normalizer.clean_text(value)

        if not text:
            return "", ""

        text = text.replace("　", "")
        text = text.replace(" ", "")
        text = text.replace("/", "")
        text = text.replace("／", "")
        text = text.replace("・", "")
        text = text.replace("投", "")
        text = text.replace("打", "")
        text = text.replace("R", "右").replace("r", "右")
        text = text.replace("L", "左").replace("l", "左")

        chars = [c for c in text if c in ["右", "左", "両"]]

        if len(chars) >= 2:
            return chars[0], chars[1]

        if len(chars) == 1:
            return chars[0], ""

        return "", ""

    @staticmethod
    def normalize_height(value):
        text = Normalizer.clean_text(value)
        text = text.replace("cm", "").replace("ＣＭ", "").replace("㎝", "")
        return text.strip()

    @staticmethod
    def normalize_weight(value):
        text = Normalizer.clean_text(value)
        text = text.replace("kg", "").replace("ＫＧ", "").replace("㎏", "")
        return text.strip()
    @staticmethod
    def to_half_width_number(text):
        table = str.maketrans("０１２３４５６７８９", "0123456789")
        return str(text).translate(table)

    @staticmethod
    def to_full_width_number(text):
        table = str.maketrans("0123456789", "０１２３４５６７８９")
        return str(text).translate(table)

    @staticmethod
    def normalize_back_number(value):
        """
        背番号：半角数字に統一
        例：１２ → 12、０７ → 7
        """
        text = Normalizer.clean_text(value)

        if not text:
            return ""

        text = Normalizer.to_half_width_number(text)
        text = text.replace("番", "").replace("号", "")
        text = text.strip()

        if text.isdigit():
            return str(int(text))

        return text

    @staticmethod
    def normalize_grade(value):
        """
        学年：全角数字＋年に統一
        例：1 → １年、１年 → １年、一 → １年
        """
        text = Normalizer.clean_text(value)

        if not text:
            return ""

        text = text.replace("　", "").replace(" ", "")
        text = text.replace("学年", "").replace("年生", "").replace("年", "")

        kanji_map = {
            "一": "1",
            "二": "2",
            "三": "3",
            "四": "4",
            "壱": "1",
            "弐": "2",
            "参": "3",
        }

        for k, v in kanji_map.items():
            text = text.replace(k, v)

        text = Normalizer.to_half_width_number(text)

        if text.isdigit():
            return Normalizer.to_full_width_number(str(int(text))) + "年"

        return Normalizer.to_full_width_number(text) + "年"

    @staticmethod
    def fill_same_marks(records, fields):
        """
        「〃」「同上」などを直前の値で補完する
        """
        last_values = {field: "" for field in fields}

        for record in records:
            for field in fields:
                value = record.get(field, "")

                if Normalizer.is_same_mark(value):
                    record[field] = last_values.get(field, "")
                elif value != "":
                    last_values[field] = value

        return records