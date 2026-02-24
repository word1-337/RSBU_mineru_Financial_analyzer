"""
agent.py — Агент анализа финансовой устойчивости (единый файл).

Запуск:
    python agent.py

Браузер откроется на http://localhost:8501
"""

import sys
from pathlib import Path
from io import StringIO

import pandas as pd
from bs4 import BeautifulSoup
from mineru.cli.common import do_parse, read_fn


# ══════════════════════════════════════════════════════════════
#  ПУТИ
# ══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
SOURCE_DIR = BASE_DIR / "source"
OUT_DIR = BASE_DIR / "new_out"
RESULTS_DIR = BASE_DIR / "results"

OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════
#  СЛОВАРИ КОДОВ И ПОКАЗАТЕЛЕЙ
# ══════════════════════════════════════════════════════════════

CODE_DESCRIPTIONS = {
    # баланс, актив
    "1100": "Итого внеоборотные активы (раздел I актива баланса)",
    "1150": "Основные средства",
    "1170": "Долгосрочные финансовые вложения",
    "1200": "Итого оборотные активы (раздел II актива баланса)",
    "1210": "Запасы",
    "1230": "Дебиторская задолженность",
    "1240": "Краткосрочные финансовые вложения",
    "1250": "Денежные средства и денежные эквиваленты",
    "1600": "Валюта баланса (итог актива)",
    # баланс, пассив
    "1300": "Итого капитал и резервы (собственный капитал)",
    "1400": "Итого долгосрочные обязательства (раздел IV пассива)",
    "1500": "Итого краткосрочные обязательства (раздел V пассива)",
    "1530": "Доходы будущих периодов (краткосрочные)",
    "1540": "Оценочные обязательства (краткосрочные)",
    "1550": "Прочие краткосрочные обязательства",
    "1700": "Баланс (итог пассива)",
    # отчёт о финансовых результатах
    "2110": "Выручка",
    "2120": "Себестоимость продаж",
    "2200": "Прибыль (убыток) от продаж",
    "2220": "Управленческие расходы",
    "2300": "Прибыль (убыток) до налогообложения",
    "2330": "Проценты к уплате",
    "2400": "Чистая прибыль (убыток) отчетного периода",
}

NEEDED_CODES = set(CODE_DESCRIPTIONS.keys())

RATIO_DESCRIPTIONS = {
    "currentratio": "Коэффициент текущей ликвидности (1200 / (1500 - 1530))",
    "quickratio": "Коэффициент быстрой ликвидности ((1200 - 1210) / 1500)",
    "koeffindep": "Коэффициент автономии (1300 / 1600)",
    "perccovratio": (
        "Доля активов, покрытых собственным капиталом и долгосрочными "
        "обязательствами ((1300 + 1400) / 1600)"
    ),
    "equityratio": (
        "Доля собственного капитала в устойчивых источниках (1300 / (1300 + 1400))"
    ),
    "finlevratio": "Коэффициент финансового левериджа ((1400 + 1500) / 1300)",
    "maneuvcoef": (
        "Коэффициент манёвренности собственного капитала ((1300 - 1100) / 1300)"
    ),
    "constassetratio": "Доля внеоборотных активов в валюте баланса (1100 / 1600)",
    "coefofownfunds": (
        "Коэффициент обеспеченности собственными оборотными средствами "
        "((1300 - 1100) / 1200)"
    ),
    "net_margin": "Чистая маржа (2400 / 2110)",
    "operating_margin": "Операционная маржа (2200 / 2110)",
    "roe_like": "Рентабельность активов/капитала (2400 / 1600, без усреднения)",
    "interest_coverage": "Покрытие процентов ((2300 + |2330|) / |2330|)",
    "normofprib": "Маржа чистой прибыли (2400 / 2110)",
}


# ══════════════════════════════════════════════════════════════
#  УТИЛИТЫ
# ══════════════════════════════════════════════════════════════

def parse_number(x):
    """Преобразовать строку вида '1 234', '(5 678)', '' в float или None."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = str(x).replace(" ", "").replace("\u00a0", "")
    s = s.replace("(", "-").replace(")", "")
    s = s.replace(",", ".")
    if s == "" or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def growth_rate(current, previous):
    """Темп прироста (current / previous - 1) в долях."""
    if current is None or previous is None:
        return None
    try:
        current = float(current)
        previous = float(previous)
    except (TypeError, ValueError):
        return None
    if previous == 0:
        return None
    return current / previous - 1.0


def run_mineru(pdf_path: Path, out_dir: Path):
    """Запустить MinerU для одного PDF."""
    do_parse(
        output_dir=str(out_dir),
        pdf_file_names=[pdf_path.stem],
        pdf_bytes_list=[read_fn(pdf_path)],
        p_lang_list=["ru"],
        backend="pipeline",
        parse_method="auto",
        formula_enable=True,
        table_enable=True,
    )


def find_md_path(pdf_stem: str, out_dir: Path) -> Path:
    """Найти <stem>.md, сгенерированный MinerU."""
    md_path_auto = out_dir / pdf_stem / "auto" / f"{pdf_stem}.md"
    md_path_plain = out_dir / pdf_stem / f"{pdf_stem}.md"
    if md_path_auto.is_file():
        return md_path_auto
    if md_path_plain.is_file():
        return md_path_plain
    raise FileNotFoundError(
        f"{pdf_stem}.md не найден ни в {md_path_auto}, ни в {md_path_plain}"
    )


def extract_codes_from_md(md_path: Path) -> dict:
    """Прочитать .md, найти HTML-таблицы и собрать значения по нужным кодам."""
    text = md_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(text, "html.parser")
    tables = soup.find_all("table")
    codes = {}

    for tbl in tables:
        try:
            df = pd.read_html(StringIO(str(tbl)))[0]
        except Exception:
            continue

        if df.shape[1] < 4:
            continue

        df.columns = [str(c).strip() for c in df.columns]

        code_col_name = None
        for col in df.columns:
            if "код" in col.lower():
                code_col_name = col
                break

        if code_col_name is None:
            first_row = df.iloc[0]
            for col in df.columns:
                if "код" in str(first_row[col]).lower():
                    code_col_name = col
                    df = df.iloc[1:].reset_index(drop=True)
                    break

        if code_col_name is None:
            continue

        current_col_name = df.columns[-2]
        prev_col_name = df.columns[-1]

        for _, row in df.iterrows():
            code_val = row[code_col_name]
            if pd.isna(code_val):
                continue
            code_str = str(code_val).strip()
            if code_str not in NEEDED_CODES:
                continue

            current_val = parse_number(row[current_col_name])
            prev_val = parse_number(row[prev_col_name])

            if code_str not in codes:
                codes[code_str] = {"current": None, "previous": None}
            if current_val is not None:
                codes[code_str]["current"] = current_val
            if prev_val is not None:
                codes[code_str]["previous"] = prev_val

    return codes


def calc_financial_ratios_from_codes(codes: dict) -> dict:
    """Рассчитать коэффициенты финансовой устойчивости и динамику."""

    def v_cur(code):
        return codes.get(code, {}).get("current")

    def v_prev(code):
        return codes.get(code, {}).get("previous")

    VA = v_cur("1100"); OA = v_cur("1200"); A = v_cur("1600")
    SK = v_cur("1300"); DO = v_cur("1400"); KO = v_cur("1500")
    DBP = v_cur("1530"); V = v_cur("2110"); PrProd = v_cur("2200")
    PrDoNal = v_cur("2300"); ProcKUp = v_cur("2330"); ChP = v_cur("2400")
    Z = v_cur("1210")

    levels = {}

    if OA is not None and KO is not None and DBP is not None and (KO - DBP) != 0:
        levels["currentratio"] = OA / (KO - DBP)
    if OA is not None and Z is not None and KO not in (None, 0):
        levels["quickratio"] = (OA - Z) / KO
    if SK is not None and A not in (None, 0):
        levels["koeffindep"] = SK / A
    if SK is not None and DO is not None and A not in (None, 0):
        levels["perccovratio"] = (SK + DO) / A
    if SK is not None and DO is not None and (SK + DO) != 0:
        levels["equityratio"] = SK / (SK + DO)
    if SK not in (None, 0) and DO is not None and KO is not None:
        levels["finlevratio"] = (DO + KO) / SK
    if SK not in (None, 0) and VA is not None:
        levels["maneuvcoef"] = (SK - VA) / SK
    if VA is not None and A not in (None, 0):
        levels["constassetratio"] = VA / A
    if OA not in (None, 0) and SK is not None and VA is not None:
        levels["coefofownfunds"] = (SK - VA) / OA
    if V not in (None, 0) and ChP is not None:
        levels["net_margin"] = ChP / V
        levels["normofprib"] = ChP / V
    if V not in (None, 0) and PrProd is not None:
        levels["operating_margin"] = PrProd / V
    if A not in (None, 0) and ChP is not None:
        levels["roe_like"] = ChP / A
    if ProcKUp is not None and ProcKUp != 0 and PrDoNal is not None:
        levels["interest_coverage"] = (PrDoNal + abs(ProcKUp)) / abs(ProcKUp)

    growth = {}
    for code in sorted(NEEDED_CODES):
        gr = growth_rate(v_cur(code), v_prev(code))
        if gr is not None:
            growth[f"growth_{code}"] = gr

    return {"levels": levels, "growth": growth}


def _score_linear(x, xmin, xmax, reverse=False):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if not reverse:
        if x <= xmin: return 0.0
        if x >= xmax: return 1.0
        return (x - xmin) / (xmax - xmin)
    else:
        if x <= xmin: return 1.0
        if x >= xmax: return 0.0
        return (xmax - x) / (xmax - xmin)


def calc_fsi_index(levels: dict) -> dict:
    """Интегральный показатель финансовой устойчивости (FSI) 0..1."""
    scores = {
        "currentratio":    _score_linear(levels.get("currentratio"),    1.0, 2.5),
        "quickratio":      _score_linear(levels.get("quickratio"),      0.7, 1.5),
        "koeffindep":      _score_linear(levels.get("koeffindep"),      0.3, 0.6),
        "perccovratio":    _score_linear(levels.get("perccovratio"),    0.6, 0.9),
        "equityratio":     _score_linear(levels.get("equityratio"),     0.3, 0.7),
        "finlevratio":     _score_linear(levels.get("finlevratio"),     1.0, 3.0, reverse=True),
        "maneuvcoef":      _score_linear(levels.get("maneuvcoef"),      0.0, 0.3),
        "constassetratio": _score_linear(levels.get("constassetratio"), 0.6, 0.9, reverse=True),
        "coefofownfunds":  _score_linear(levels.get("coefofownfunds"),  0.0, 0.3),
        "net_margin":      _score_linear(levels.get("net_margin"),      0.02, 0.2),
    }
    valid = [v for v in scores.values() if v is not None]
    fsi = sum(valid) / len(valid) if valid else None
    return {"scores": scores, "fsi": fsi}


def write_result_txt(pdf_path, codes, levels, growth, fsi_info):
    """Сохранить результат в results/<stem>.txt."""
    lines = [f"Файл PDF: {pdf_path.name}", ""]

    lines.append("=== Строки отчётности (баланс и ОФР) ===")
    for code in sorted(NEEDED_CODES):
        desc = CODE_DESCRIPTIONS.get(code, "")
        vals = codes.get(code)
        cur  = vals.get("current")  if vals else None
        prev = vals.get("previous") if vals else None
        lines.append(
            f"Код {code}: {desc}\n"
            f"  Текущий период: {cur}\n"
            f"  Прошлый период: {prev}"
        )

    lines += ["", "=== Показатели финансовой устойчивости (уровни) ==="]
    for name, value in levels.items():
        lines.append(f"{name}: {value}  # {RATIO_DESCRIPTIONS.get(name, '')}")

    lines += [
        "", "=== Динамика ключевых показателей (темп прироста) ===",
        "Темп прироста рассчитывается как (текущий / прошлый - 1), в долях.",
    ]
    for key, val in growth.items():
        code = key.split("_", 1)[1]
        lines.append(f"{key}: {val}  # {code} — {CODE_DESCRIPTIONS.get(code, '')}")

    lines += ["", "=== Интегральный показатель финансовой устойчивости ==="]
    lines.append(f"FSI (0..1): {fsi_info.get('fsi')}")
    lines += ["", "Оценки отдельных коэффициентов (0..1):"]
    for name, score in fsi_info.get("scores", {}).items():
        lines.append(f"{name}: {score}  # {RATIO_DESCRIPTIONS.get(name, '')}")

    txt_path = RESULTS_DIR / f"{pdf_path.stem}.txt"
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Результат сохранён в {txt_path}")


def process_pdf(pdf_path: Path):
    """Полный пайплайн: PDF → MinerU → коэффициенты → .txt отчёт."""
    print(f"Обработка: {pdf_path.name}")
    run_mineru(pdf_path, OUT_DIR)
    md_path = find_md_path(pdf_path.stem, OUT_DIR)
    codes = extract_codes_from_md(md_path)
    ratios_all = calc_financial_ratios_from_codes(codes)
    fsi_info = calc_fsi_index(ratios_all["levels"])
    write_result_txt(pdf_path, codes, ratios_all["levels"], ratios_all["growth"], fsi_info)


# ══════════════════════════════════════════════════════════════
#  STREAMLIT UI
# ══════════════════════════════════════════════════════════════

def run_ui():
    import streamlit as st
    import ollama

    st.set_page_config(page_title="Агент финансовой устойчивости", layout="wide")
    st.title("Агент анализа финансовой устойчивости")
    st.markdown(
        "Загрузи PDF с российской бухгалтерской отчётностью (баланс, ОФР, ОДДС). "
        "Файл будет сохранён в папку `source`, результат анализа — в папку `results`."
    )

    uploaded = st.file_uploader("Выбери файл PDF", type=["pdf"])

    if uploaded is not None:
        source_dir = BASE_DIR / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = source_dir / uploaded.name
        with open(pdf_path, "wb") as f:
            f.write(uploaded.getbuffer())

        st.success(f"Файл сохранён в {pdf_path}")

        if st.button("Проанализировать этот PDF"):
            with st.spinner("Запускаю MinerU и считаю показатели... (обработка может занять до 5 минут)"):
                process_pdf(pdf_path)
            st.session_state["last_pdf_stem"] = pdf_path.stem

    if "last_pdf_stem" in st.session_state:
        stem = st.session_state["last_pdf_stem"]
        report_path = RESULTS_DIR / f"{stem}.txt"

        if report_path.is_file():
            report_text = report_path.read_text(encoding="utf-8")

            st.success(f"Анализ завершён. Результат сохранён в {report_path}")
            st.subheader("Отчёт по финансовой устойчивости")
            st.text_area("Содержимое отчёта", value=report_text, height=400)
            st.download_button(
                "Скачать отчёт (.txt)",
                data=report_text.encode("utf-8"),
                file_name=f"{stem}.txt",
                mime="text/plain",
            )

            if "ollama_summary" not in st.session_state:
                st.session_state["ollama_summary"] = ""
            if "ollama_answer" not in st.session_state:
                st.session_state["ollama_answer"] = ""

            st.markdown("---")
            st.subheader("Краткий вывод ИИ (Ollama)")

            if st.button("Сформировать краткий вывод"):
                try:
                    with st.spinner("Генерирую вывод..."):
                        resp = ollama.chat(
                            model="qwen2.5:32b",
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        "Ты финансовый аналитик. Отвечай кратко, структурировано, "
                                        "на русском языке."
                                    ),
                                },
                                {
                                    "role": "user",
                                    "content": (
                                        "Сделай краткий вывод о финансовой устойчивости компании "
                                        "на основе следующего отчёта: оцени уровень риска "
                                        "(низкий/средний/высокий), укажи ключевые сильные и "
                                        f"слабые стороны.\n\n{report_text}"
                                    ),
                                },
                            ],
                        )
                        st.session_state["ollama_summary"] = resp["message"]["content"]
                except Exception as e:
                    st.error(f"Ошибка при обращении к Ollama: {e}")

            if st.session_state["ollama_summary"]:
                st.write(st.session_state["ollama_summary"])

            st.markdown("---")
            st.subheader("Задать свой вопрос ИИ по отчёту")

            question = st.text_input(
                "Вопрос по устойчивости (например: 'как изменилась выручка?' )",
                key="question_input",
            )

            if st.button("Спросить ИИ") and question:
                try:
                    with st.spinner("Отвечаю..."):
                        resp_q = ollama.chat(
                            model="qwen2.5:32b",
                            messages=[
                                {
                                    "role": "system",
                                    "content": "Ты финансовый аналитик. Отвечай на русском.",
                                },
                                {
                                    "role": "user",
                                    "content": (
                                        "Ответь на вопрос по следующему отчёту о финансовой "
                                        f"устойчивости.\n\nОТЧЁТ:\n{report_text}\n\nВОПРОС: {question}"
                                    ),
                                },
                            ],
                        )
                        st.session_state["ollama_answer"] = resp_q["message"]["content"]
                except Exception as e:
                    st.error(f"Ошибка при обращении к Ollama: {e}")

            if st.session_state["ollama_answer"]:
                st.write(st.session_state["ollama_answer"])
        else:
            st.info("Нажми кнопку 'Проанализировать этот PDF', чтобы получить отчёт.")


# ══════════════════════════════════════════════════════════════
#  ТОЧКА ВХОДА
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if "streamlit" in sys.modules:
        # Запущен через `streamlit run agent.py` — показываем UI
        run_ui()
    else:
        # Запущен через `python agent.py` — автоматически стартуем streamlit
        import subprocess
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", __file__],
            check=True,
        )
