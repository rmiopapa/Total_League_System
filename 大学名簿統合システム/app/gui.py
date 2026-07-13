import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES

from app.config import APP_NAME, APP_VERSION, TEMPLATE_FILE_NAME, DEFAULT_OUTPUT_FILE
from app.excel_reader import ExcelReader
from app.header_detector import HeaderDetector
from app.data_extractor import DataExtractor
from app.exporter import ExcelExporter
from app.settings import SettingsManager


GUI_TITLE = "大学名簿統合システム　中国地区大学準硬式野球連盟"
UI_FONT = ("Meiryo", 18)
UI_FONT_BOLD = ("Meiryo", 18, "bold")
LOG_FONT = ("Consolas", 18)


class CTkDnD(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)


def clean_drop_path(value):
    value = value.strip()
    if value.startswith("{") and value.endswith("}"):
        value = value[1:-1]
    return value


def run_app():
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")

    root = CTkDnD()
    root.title(GUI_TITLE)
    root.geometry("1920x1280")

    def maximize_window():
        try:
            root.state("zoomed")
        except tk.TclError:
            root.attributes("-zoomed", True)

    maximize_window()
    root.after(100, maximize_window)

    input_folder_var = tk.StringVar()
    output_file_var = tk.StringVar()
    single_file_var = tk.StringVar()

    overwrite_var = tk.BooleanVar(value=True)
    save_log_var = tk.BooleanVar(value=True)
    process_mode_var = tk.StringVar(value="all")

    settings = SettingsManager.load()

    input_folder_var.set(settings.get("last_input_folder", ""))
    output_file_var.set(settings.get("last_output_file", ""))
    overwrite_var.set(settings.get("overwrite", True))
    save_log_var.set(settings.get("save_log", True))

    def log(message):
        log_text.insert("end", message + "\n")
        log_text.see("end")

    def get_template_file():
        folder = input_folder_var.get()
        if not folder:
            return None
        return Path(folder) / TEMPLATE_FILE_NAME

    def get_excel_files():
        folder = input_folder_var.get()
        if not folder:
            return []

        path = Path(folder)
        return sorted([
            f for f in path.glob("*.xlsx")
            if not f.name.startswith("~$")
            and f.name != TEMPLATE_FILE_NAME
        ])

    def get_target_files():
        if process_mode_var.get() == "single":
            file_path = single_file_var.get()
            if not file_path:
                return []
            return [Path(file_path)]

        return get_excel_files()

    def set_input_folder(folder):
        input_folder_var.set(str(folder))

        if not output_file_var.get():
            output_file_var.set(str(Path(folder) / DEFAULT_OUTPUT_FILE))

        scan_excel_files()

    def scan_excel_files():
        log_text.delete("1.0", "end")

        folder = input_folder_var.get()
        if not folder:
            return

        files = get_excel_files()
        template_file = get_template_file()

        log(f"入力フォルダ: {folder}")
        log(f"テンプレート: {template_file}")

        if template_file and template_file.exists():
            log("テンプレート確認: あり")
        else:
            log("テンプレート確認: なし ※テンプレートなしで出力します")

        log(f"Excelファイル検出数: {len(files)} 件")

        for f in files:
            log(f" - {f.name}")

        if not files:
            log("Excelファイルが見つかりませんでした。")

    def select_input_folder():
        folder = filedialog.askdirectory(title="入力フォルダを選択")
        if folder:
            set_input_folder(folder)

    def select_single_file():
        initial_dir = input_folder_var.get() or None
        file_path = filedialog.askopenfilename(
            title="更新する大学ファイルを選択",
            initialdir=initial_dir,
            filetypes=[("Excelファイル", "*.xlsx")]
        )
        if file_path:
            single_file_var.set(file_path)

            if not input_folder_var.get():
                input_folder_var.set(str(Path(file_path).parent))

            log("")
            log(f"1大学更新ファイル: {file_path}")

    def select_output_file():
        initial_dir = input_folder_var.get() or None
        file_path = filedialog.asksaveasfilename(
            title="出力ファイルを指定",
            initialdir=initial_dir,
            defaultextension=".xlsx",
            filetypes=[("Excelファイル", "*.xlsx")],
            initialfile=DEFAULT_OUTPUT_FILE
        )
        if file_path:
            output_file_var.set(file_path)

    def on_drop_folder(event):
        dropped = clean_drop_path(event.data)
        path = Path(dropped)

        if path.is_dir():
            set_input_folder(path)
            log("")
            log("フォルダをドラッグ＆ドロップで設定しました。")
            log(f"設定フォルダ: {path}")
        else:
            messagebox.showwarning(
                "確認",
                "入力フォルダとして使用するフォルダをドロップしてください。"
            )

    def on_mode_change():
        mode = process_mode_var.get()

        if mode == "all":
            single_file_entry.configure(state="disabled")
            single_file_button.configure(state="disabled")
            log("")
            log("処理モード: 全大学更新")
        else:
            single_file_entry.configure(state="normal")
            single_file_button.configure(state="normal")
            log("")
            log("処理モード: 1大学のみ更新")

    def run_process():
        input_folder = input_folder_var.get()
        output_file = output_file_var.get()
        mode = process_mode_var.get()

        if not input_folder:
            messagebox.showwarning("確認", "入力フォルダを選択してください。")
            return

        if not output_file:
            messagebox.showwarning("確認", "出力ファイルを指定してください。")
            return

        if mode == "single" and not single_file_var.get():
            messagebox.showwarning("確認", "更新する大学ファイルを選択してください。")
            return

        files = get_target_files()

        if not files:
            messagebox.showwarning("確認", "処理対象のExcelファイルが見つかりません。")
            return

        template_file = get_template_file()

        log("")
        log(f"{APP_NAME} {APP_VERSION} 処理を開始します。")
        log(f"処理モード: {'1大学のみ更新' if mode == 'single' else '全大学更新'}")
        log(f"出力ファイル: {output_file}")
        log(f"テンプレート: {template_file}")
        log(f"既存シート上書き: {overwrite_var.get()}")
        log(f"ログ保存: {save_log_var.get()}")

        university_records = {}

        for file_path in files:
            try:
                if file_path.name.startswith("~$"):
                    continue

                if file_path.name == TEMPLATE_FILE_NAME:
                    continue

                reader = ExcelReader(file_path)
                summary = reader.read_summary()

                detector = HeaderDetector(summary["rows"])
                header_info = detector.detect()

                if header_info["header_row"] is None:
                    log("")
                    log(f"警告: {file_path.name} は見出し行を判定できなかったためスキップしました。")
                    continue

                all_rows = reader.read_all_rows()

                extractor = DataExtractor(all_rows, header_info)
                records = extractor.extract()

                university_name = summary["university_name"]
                university_records[university_name] = records

                log("")
                log("=" * 70)
                log(f"ファイル: {summary['file_name']}")
                log(f"大学名: {university_name}")
                log(f"見出し行: {header_info['header_row']} 行目")
                log(f"抽出件数: {len(records)} 件")

                if records:
                    first = records[0]
                    log(
                        "先頭データ: "
                        f"背番号={first.get('背番号', '')} / "
                        f"氏名={first.get('氏名', '')} / "
                        f"略名={first.get('略名', '')} / "
                        f"スタッフ分類={first.get('スタッフ分類', '')} / "
                        f"高校={first.get('高校', '')} / "
                        f"守備位置={first.get('守備位置', '')} / "
                        f"投={first.get('投', '')} / "
                        f"打={first.get('打', '')}"
                    )

            except Exception as e:
                log(f"エラー: {file_path.name} - {e}")

        if not university_records:
            messagebox.showwarning("確認", "出力できるデータがありませんでした。")
            return

        try:
            exporter = ExcelExporter(
                output_file=output_file,
                overwrite=overwrite_var.get(),
                template_file=template_file
            )
            exporter.save(university_records)

            SettingsManager.save({
                "last_input_folder": input_folder_var.get(),
                "last_output_file": output_file_var.get(),
                "overwrite": overwrite_var.get(),
                "save_log": save_log_var.get(),
            })

            log("")
            log("Excel出力が完了しました。")
            log(f"保存先: {output_file}")

            messagebox.showinfo("完了", "Excel出力が完了しました。")

        except Exception as e:
            log("")
            log(f"出力エラー: {e}")
            messagebox.showerror("エラー", f"Excel出力に失敗しました。\n\n{e}")

    title_label = ctk.CTkLabel(
        root,
        text=GUI_TITLE,
        font=UI_FONT_BOLD
    )
    title_label.pack(anchor="w", padx=16, pady=(14, 8))

    mode_frame = ctk.CTkFrame(root)
    mode_frame.pack(fill="x", padx=16, pady=(0, 10))

    ctk.CTkLabel(mode_frame, text="処理モード", font=UI_FONT_BOLD).pack(
        side="left", padx=(12, 4), pady=8
    )

    ctk.CTkRadioButton(
        mode_frame,
        text="全大学更新",
        variable=process_mode_var,
        value="all",
        command=on_mode_change,
        font=UI_FONT
    ).pack(side="left", padx=12, pady=8)

    ctk.CTkRadioButton(
        mode_frame,
        text="1大学のみ更新",
        variable=process_mode_var,
        value="single",
        command=on_mode_change,
        font=UI_FONT
    ).pack(side="left", padx=12, pady=8)

    ctk.CTkLabel(root, text="入力フォルダ", font=UI_FONT).pack(anchor="w", padx=16)

    input_frame = ctk.CTkFrame(root, fg_color="transparent")
    input_frame.pack(fill="x", padx=16, pady=(2, 8))

    ctk.CTkEntry(input_frame, textvariable=input_folder_var, font=UI_FONT).pack(
        side="left", fill="x", expand=True
    )
    ctk.CTkButton(input_frame, text="参照", width=110, command=select_input_folder, font=UI_FONT).pack(
        side="left", padx=(8, 0)
    )

    drop_label = ctk.CTkLabel(
        root,
        text="📁 ここへ入力フォルダをドラッグ＆ドロップ",
        font=UI_FONT,
        height=64,
        fg_color=("#f5f5f5", "#2b2b2b"),
        corner_radius=6
    )
    drop_label.pack(fill="x", padx=16, pady=(0, 10))

    TkinterDnD.DnDWrapper.drop_target_register(drop_label, DND_FILES)
    TkinterDnD.DnDWrapper.dnd_bind(drop_label, "<<Drop>>", on_drop_folder)

    ctk.CTkLabel(root, text="1大学更新ファイル", font=UI_FONT).pack(anchor="w", padx=16)

    single_file_frame = ctk.CTkFrame(root, fg_color="transparent")
    single_file_frame.pack(fill="x", padx=16, pady=(2, 10))

    single_file_entry = ctk.CTkEntry(
        single_file_frame,
        textvariable=single_file_var,
        font=UI_FONT,
        state="disabled"
    )
    single_file_entry.pack(side="left", fill="x", expand=True)

    single_file_button = ctk.CTkButton(
        single_file_frame,
        text="参照",
        width=110,
        command=select_single_file,
        state="disabled",
        font=UI_FONT
    )
    single_file_button.pack(side="left", padx=(8, 0))

    ctk.CTkLabel(root, text="出力ファイル", font=UI_FONT).pack(anchor="w", padx=16)

    output_frame = ctk.CTkFrame(root, fg_color="transparent")
    output_frame.pack(fill="x", padx=16, pady=(2, 10))

    ctk.CTkEntry(output_frame, textvariable=output_file_var, font=UI_FONT).pack(
        side="left", fill="x", expand=True
    )
    ctk.CTkButton(output_frame, text="参照", width=110, command=select_output_file, font=UI_FONT).pack(
        side="left", padx=(8, 0)
    )

    option_frame = ctk.CTkFrame(root, fg_color="transparent")
    option_frame.pack(fill="x", padx=16, pady=(0, 8))

    ctk.CTkCheckBox(
        option_frame,
        text="既存の大学シートは上書きする",
        variable=overwrite_var,
        font=UI_FONT
    ).pack(anchor="w")

    ctk.CTkCheckBox(
        option_frame,
        text="処理ログを保存する",
        variable=save_log_var,
        font=UI_FONT
    ).pack(anchor="w")

    ctk.CTkButton(
        root,
        text="名簿統合開始",
        command=run_process,
        width=220,
        height=54,
        font=UI_FONT_BOLD
    ).pack(pady=8)

    ctk.CTkLabel(root, text="処理ログ", font=UI_FONT).pack(anchor="w", padx=16)

    log_text = ctk.CTkTextbox(root, height=260, font=LOG_FONT)
    log_text.pack(fill="both", expand=True, padx=16, pady=(2, 16))

    if input_folder_var.get():
        scan_excel_files()

    root.mainloop()
