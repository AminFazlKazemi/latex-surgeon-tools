#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import shutil
import subprocess
import sys
import threading
import queue
import json
import time
from pathlib import Path
from tqdm import tqdm
import concurrent.futures

# ============================================================================
# مسیرها
# ============================================================================
SOURCE = Path(r"K:\kazemi\papers\poetry\latex_surgeon.py")
BACKUP = SOURCE.with_suffix(".py.bak")
TARGETS = [
    r"K:\kazemi\papers\poetry\She-rAI\SherAI_Paper_English_Final.tex",
    r"K:\kazemi\papers\poetry\She-rAI\sherai_guide_final.tex",
    r"K:\kazemi\papers\poetry\She-rAI\SherAI_Paper_Persian_Final.tex",
]
DEBT_FILE = Path(r"K:\kazemi\papers\poetry\.latex_technical_debt.json")

# ============================================================================
# نمایش قابلیت‌های تشخیصی در ابتدا
# ============================================================================

def show_diagnostic_capabilities():
    """نمایش آمار پوشش خطاها در ابتدای اجرا"""
    print("\n" + "=" * 80)
    print("🩺 LaTeX Surgeon - سامانه تشخیص و جراحی خطاهای لاتکس")
    print("=" * 80)
    print("\n📊 آمار پوشش خطاها بر اساس سطح:")
    print()
    print("  ✅ سطح جدی (CRITICAL)   : ۱۹ نوع خطا (مانع تولید PDF)")
    print("     شامل: Missing \\begin{document}, Missing package, Undefined control sequence,")
    print("     Emergency stop, Brace imbalance, Fatal error و ...")
    print()
    print("  ⚠️ سطح متوسط (MODERATE)  : ۱۱ نوع خطا (کیفیت خروجی را کاهش می‌دهد)")
    print("     شامل: Undefined citation/reference, Biber required, Option clash,")
    print("     Rerun needed, Empty bibliography و ...")
    print()
    print("  ℹ️ سطح سطحی (COSMETIC)   : ۷ نوع خطا (هشدارهای جزئی)")
    print("     شامل: Overfull/Underfull hbox, Hyperref/TOC warnings, Float warnings و ...")
    print()
    print("📌 استراتژی جراحی:")
    print("   فقط خطاهای سطح جدی به‌طور خودکار برطرف می‌شوند.")
    print("   خطاهای سطح متوسط و سطحی در فایل .latex_technical_debt.json ذخیره می‌شوند.")
    print("\n" + "=" * 80)
    print()

# ============================================================================
# توابع کمکی برای دریافت ورودی در اسپایدر
# ============================================================================

def get_user_choice(prompt, options, default="medium"):
    """تلاش برای دریافت ورودی از کاربر. در صورت خطا، مقدار پیش‌فرض را برمی‌گرداند."""
    try:
        choice = input(prompt).strip()
        if choice in options:
            return options[choice]
        else:
            print(f"ورودی نامعتبر. استفاده از مقدار پیش‌فرض: {default}")
            return default
    except (EOFError, OSError, AttributeError):
        print(f"\n⚠️ محیط تعاملی پشتیبانی نمی‌شود. استفاده از سطح پیش‌فرض: {default}")
        return default

def get_level_from_user():
    """دریافت سطح جراحی از کاربر با پشتیبانی از اسپایدر."""
    print("🩺 LaTeX Surgeon - انتخاب سطح جراحی")
    print("=" * 60)
    print("سطوح خطا:")
    print("  ❌ جدی (Critical)   : مانع تولید PDF (مثل Missing \\begin{document})")
    print("  ⚠️ متوسط (Moderate) : کیفیت را کاهش می‌دهد (مثل ارجاع تعریف‌نشده)")
    print("  ℹ️ سطحی (Cosmetic)  : هشدارهای جزئی (مثل Overfull hbox)")
    print("\nسطح جراحی:")
    print("  1. quick    : فقط رفع خطاهای جدی (حدود ۵ دور)")
    print("  2. medium   : رفع خطاهای جدی و متوسط (حدود ۲۰ دور)")
    print("  3. full     : رفع تمام خطاها (حدود ۵۰ دور)")
    print("  4. complete : بررسی کامل (۲۵۰ دور)")

    options = {"1": "quick", "2": "medium", "3": "full", "4": "complete"}
    default = "medium"

    import argparse
    parser = argparse.ArgumentParser(description="LaTeX Surgeon - Diagnostic and Surgical Tool")
    parser.add_argument("--level", choices=["quick", "medium", "full", "complete"], default=None,
                        help="سطح جراحی: quick (سریع), medium (متوسط), full (کامل), complete (همه)")
    parser.add_argument("--no-backup", action="store_true", help="از فایل بکاپ نگیر")
    args, unknown = parser.parse_known_args()

    if args.level:
        print(f"\n✅ سطح انتخابی از خط فرمان: {args.level}")
        return args.level, args.no_backup

    choice = get_user_choice("\nعدد مورد نظر را وارد کنید (1/2/3/4): ", options, default)
    print(f"\n✅ سطح انتخابی: {choice}")
    return choice, False

# ============================================================================
# بررسی اینکه آیا پچ‌ها قبلاً اعمال شده‌اند
# ============================================================================

def is_patched(content):
    """بررسی می‌کند که آیا پچ‌های اصلی قبلاً اعمال شده‌اند."""
    markers = [
        "def propose_missing_document_boundary",
        "def run_biber",
        "def compile_once_enhanced",
        "def propose_csquotes_persian_fix",
        "PROGRESS:{stage_no}/{V15_MAX_STAGES}",
    ]
    for marker in markers:
        if marker not in content:
            return False
    return True

# ============================================================================
# پچ‌های فایل latex_surgeon.py
# ============================================================================

def apply_patches(content):
    """اعمال تمام تغییرات روی محتوای latex_surgeon.py، فقط در صورتی که قبلاً اعمال نشده باشند."""
    
    # اگر قبلاً پچ شده، بدون تغییر برگردان
    if is_patched(content):
        print("✅ پچ‌ها قبلاً در فایل latex_surgeon.py اعمال شده‌اند. نیازی به تغییر مجدد نیست.")
        return content

    print("🔧 اعمال پچ‌های جدید روی latex_surgeon.py...")

    # 1. افزودن تابع propose_missing_document_boundary
    if "def propose_missing_document_boundary" not in content:
        func = '''
def propose_missing_document_boundary(project: ProjectInfo, log: str) -> Optional[RepairProposal]:
    """Insert missing \\\\begin{document} or \\\\end{document} if absent."""
    source = read_text(project.tex)
    begins, ends = document_signature(source)
    if begins == 1 and ends == 1:
        return None
    new_source = source
    if begins == 0:
        pos = preamble_end(source)
        if pos < 0:
            m = re.search(r"\\\\documentclass(?:\\\\[[^\\\\]]*\\\\])?\\\\{[^}]+\\\\}", source)
            if m:
                pos = m.end()
            else:
                pos = 0
        if pos >= 0:
            new_source = new_source[:pos] + "\\\\n\\\\begin{document}\\\\n" + new_source[pos:]
            begins += 1
    if ends == 0:
        new_source = new_source.rstrip() + "\\\\n\\\\end{document}\\\\n"
        ends += 1
    if new_source == source:
        return None
    safe, reason = source_safety_check(source, new_source)
    if not safe:
        return None
    return RepairProposal(
        rule_id="ADD_MISSING_DOCUMENT_BOUNDARY",
        description="Insert missing \\\\begin{document} and/or \\\\end{document}",
        confidence=0.99,
        old_text=source,
        new_text=new_source,
        rationale="Compiler reported missing document boundary; inserting it is safe and necessary."
    )
'''
        content = content.replace("def propose_repairs(", func + "\n\ndef propose_repairs(", 1)

    # 2. افزودن تابع run_biber
    if "def run_biber" not in content:
        biber_func = '''
def run_biber(project: ProjectInfo) -> tuple[bool, str]:
    """Run Biber if .bcf exists."""
    bcf = project.root / f"{project.tex.stem}.bcf"
    if not bcf.exists():
        return False, "no .bcf file"
    try:
        subprocess.run(["biber", project.tex.stem], cwd=project.root, check=True, timeout=60,
                       capture_output=True, text=True)
        return True, "biber ran successfully"
    except Exception as exc:
        return False, str(exc)
'''
        content = content.replace("def build_until_clean_v16(", biber_func + "\n\ndef build_until_clean_v16(", 1)

    # 3. افزودن تابع compile_once_enhanced
    if "def compile_once_enhanced" not in content:
        enhanced = '''
def compile_once_enhanced(project: ProjectInfo, cfg: CompilerConfig) -> BuildResult:
    """Same as compile_once but adds --shell-escape if biblatex is used."""
    start = time.perf_counter()
    cmd = [
        project.engine,
        "-interaction=nonstopmode",
        "-file-line-error",
        "-synctex=1",
    ]
    source = read_text(project.tex)
    if re.search(r"\\\\usepackage(?:\\\\[[^\\\\]]*\\\\])?\\\\{biblatex\\\\}", source, re.I):
        cmd.append("--shell-escape")
    cmd.append(project.tex.name)
    try:
        p = subprocess.run(
            cmd,
            cwd=project.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg.timeout,
            shell=False,
        )
        log = p.stdout or ""
        pdf = project.tex.with_suffix(".pdf")
        success = p.returncode == 0 and pdf.exists()
        return BuildResult(
            success=success,
            engine=project.engine,
            returncode=p.returncode,
            log=log,
            pdf=pdf if pdf.exists() else None,
            elapsed=time.perf_counter() - start,
        )
    except Exception as exc:
        return BuildResult(
            success=False,
            engine=project.engine,
            returncode=125,
            log=f"COMPILE_ENHANCED_EXCEPTION: {type(exc).__name__}: {exc}\\n{traceback.format_exc()}",
            elapsed=time.perf_counter() - start,
        )
'''
        content = content.replace("def build_until_clean_v16(", enhanced + "\n\ndef build_until_clean_v16(", 1)

    # 4. افزودن تابع propose_csquotes_persian_fix
    if "def propose_csquotes_persian_fix" not in content:
        cs_func = '''
def propose_csquotes_persian_fix(project: ProjectInfo) -> Optional[RepairProposal]:
    source = read_text(project.tex)
    if not re.search(r"\\\\usepackage(?:\\\\[[^\\\\]]*\\\\])?\\\\{csquotes\\\\}", source, re.I):
        return None
    if not project.has_persian:
        return None
    if not re.search(r"\\\\usepackage(?:\\\\[[^\\\\]]*\\\\])?\\\\{polyglossia\\\\}", source, re.I):
        new_source = add_package_once(source, "polyglossia")
        if new_source:
            pos = new_source.find("\\\\usepackage{polyglossia}") + len("\\\\usepackage{polyglossia}")
            new_source = new_source[:pos] + "\\\\n\\\\setmainlanguage{persian}\\\\n" + new_source[pos:]
            if source_safety_check(source, new_source)[0]:
                return RepairProposal(
                    rule_id="ADD_POLYGLOSSIA_PERSIAN",
                    description="Add polyglossia with Persian language for csquotes",
                    confidence=0.95,
                    old_text=source,
                    new_text=new_source,
                    rationale="csquotes needs language support; adding polyglossia fixes it."
                )
    return None
'''
        content = content.replace("def propose_repairs(", cs_func + "\n\ndef propose_repairs(", 1)

    # 5. اصلاح extract_missing_package_names برای شناسایی فایل‌های lbx
    new_extract = '''
def extract_missing_package_names(log: str) -> list[str]:
    found: list[str] = []
    patterns = (
        r"File `([^`]+)\.sty' not found",
        r"File `([^`]+)\.lbx' not found",
        r"LaTeX Error:\\s*File `([^`]+)(?:\.sty)?' not found",
        r"I can't find file `([^`]+)(?:\.sty)?'",
        r"Package biblatex Warning: File '([^']+)\.lbx' not found",
    )
    for pattern in patterns:
        for m in re.finditer(pattern, log or "", re.I):
            name = Path(m.group(1)).name
            name = re.sub(r"\\.(sty|lbx)$", "", name, flags=re.I)
            if name not in found and re.fullmatch(r"[A-Za-z0-9_.+@-]+", name):
                found.append(name)
    return found
'''
    new_extract_escaped = new_extract.replace('\\', '\\\\')
    if "def extract_missing_package_names" in content:
        pattern = r"def extract_missing_package_names\(log: str\) -> list\[str\]:.*?(?=\n\S)"
        content = re.sub(pattern, new_extract_escaped, content, flags=re.DOTALL)

    # 6. افزودن پیام پیشرفت در build_until_clean_v15
    # اطمینان از اینکه فقط یک بار اضافه می‌شود
    if "PROGRESS:{stage_no}/{V15_MAX_STAGES}" not in content:
        content = re.sub(
            r'^(\s*_SELF_STATE\["stage_name"\] = stage_name)$',
            r'\1\n        print(f"PROGRESS:{stage_no}/{V15_MAX_STAGES}")',
            content,
            flags=re.MULTILINE
        )

    return content

# ============================================================================
# کلاس‌های کمکی برای خواندن خروجی
# ============================================================================

class OutputReader:
    def __init__(self, process, queue, label):
        self.process = process
        self.queue = queue
        self.label = label
        self.thread = threading.Thread(target=self._read_output)
        self.thread.daemon = True

    def start(self):
        self.thread.start()

    def _read_output(self):
        for line in iter(self.process.stdout.readline, ''):
            self.queue.put((self.label, line))
        self.process.stdout.close()

# ============================================================================
# سطح‌بندی خطاها (خطاهای جدی = مانع کامپایل)
# ============================================================================

def classify_errors(log: str) -> dict:
    """لاگ را تحلیل کرده و خطاها را به سه سطح تقسیم می‌کند."""
    levels = {
        "critical": [],
        "moderate": [],
        "cosmetic": [],
    }

    critical_patterns = {
        "missing_begin_document": r"Missing \\begin\{document\}",
        "missing_end_document": r"Missing \\end\{document\}",
        "missing_package": r"File `[^`]+\.sty' not found",
        "missing_lbx": r"File `[^']+\.lbx' not found",
        "missing_font": r"The font `[^']+' cannot be found",
        "runaway_argument": r"Runaway argument",
        "emergency_stop": r"Emergency stop",
        "fatal_error": r"Fatal error occurred",
        "brace_imbalance": r"Missing \} inserted",
        "environment_undefined": r"Environment .* undefined",
        "command_undefined": r"Undefined control sequence",
        "package_error": r"! Package .*? Error:",
        "latex_error": r"! LaTeX Error:",
        "file_not_found": r"File `[^`]+' not found",
        "pdf_inclusion": r"pdfTeX error",
        "engine_mismatch": r"requires XeTeX|requires LuaTeX",
        "memory_error": r"TeX capacity exceeded",
        "math_error": r"Missing \$ inserted|Bad math environment",
        "tabular_error": r"Extra alignment tab|Misplaced \\noalign",
    }

    moderate_patterns = {
        "undefined_citation": r"Citation `[^`]+' undefined",
        "undefined_reference": r"Reference `[^`]+' undefined",
        "biber_required": r"Please \(re\)run Biber",
        "biblatex_warning": r"Package biblatex Warning",
        "csquotes_persian": r"Package csquotes Warning: No style for language 'persian'",
        "shell_escape": r"restricted \\write18",
        "duplicate_package": r"Option clash for package",
        "inputenc_obsolete": r"inputenc Error",
        "rerun_needed": r"Rerun to get cross-references right",
        "empty_bibliography": r"Empty bibliography",
        "multiply_label": r"multiply-defined labels",
    }

    cosmetic_patterns = {
        "overfull_hbox": r"Overfull \\[hv]box",
        "underfull_hbox": r"Underfull \\[hv]box",
        "hyperref_warning": r"Package hyperref Warning",
        "toc_warning": r"Package tocloft Warning",
        "page_number_warning": r"Page number",
        "float_warning": r"Float too large",
        "generic_warning": r"LaTeX Warning",
    }

    for name, pat in critical_patterns.items():
        if re.search(pat, log, re.I):
            levels["critical"].append(name)

    for name, pat in moderate_patterns.items():
        if re.search(pat, log, re.I):
            levels["moderate"].append(name)

    for name, pat in cosmetic_patterns.items():
        if re.search(pat, log, re.I):
            levels["cosmetic"].append(name)

    if levels["critical"]:
        overall = "critical"
    elif levels["moderate"]:
        overall = "moderate"
    elif levels["cosmetic"]:
        overall = "cosmetic"
    else:
        overall = "healthy"

    return {
        "overall": overall,
        "levels": levels,
        "has_critical": bool(levels["critical"]),
        "has_moderate": bool(levels["moderate"]),
        "has_cosmetic": bool(levels["cosmetic"]),
    }

# ============================================================================
# تشخیص اولیه
# ============================================================================

def diagnostic_scan(target):
    """یک کامپایل سریع (۱ دور) انجام داده و خطاها را سطح‌بندی می‌کند."""
    cmd = [sys.executable, str(SOURCE), target, "--rounds", "1"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        pdf = Path(target).with_suffix(".pdf")
        pdf_created = pdf.exists()
        classification = classify_errors(log)

        if not classification["has_critical"] and pdf_created:
            classification["overall"] = "healthy"

        return {
            "target": target,
            "pdf_created": pdf_created,
            "returncode": result.returncode,
            "classification": classification,
            "log_preview": log[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {
            "target": target,
            "pdf_created": False,
            "returncode": -1,
            "classification": {"overall": "critical", "has_critical": True, "levels": {"critical": ["timeout"]}},
            "log_preview": "TIMEOUT",
        }
    except Exception as e:
        return {
            "target": target,
            "pdf_created": False,
            "returncode": -2,
            "classification": {"overall": "critical", "has_critical": True, "levels": {"critical": [str(e)]}},
            "log_preview": str(e),
        }

# ============================================================================
# تعیین تعداد دورهای جراحی
# ============================================================================

def determine_rounds(classification, level_choice):
    if classification["overall"] == "healthy":
        return 0
    if level_choice == "quick":
        return 5 if classification["has_critical"] else 0
    elif level_choice == "medium":
        return 20 if classification["has_critical"] else 5 if classification["has_moderate"] else 0
    elif level_choice == "full":
        return 50
    elif level_choice == "complete":
        return 250
    if classification["has_critical"]:
        return 30
    elif classification["has_moderate"]:
        return 10
    else:
        return 0

# ============================================================================
# ذخیره خطاهای سطح ۲ و ۳
# ============================================================================

def save_technical_debt(target, classification):
    if not classification["has_moderate"] and not classification["has_cosmetic"]:
        return
    debt = {}
    if DEBT_FILE.exists():
        try:
            with open(DEBT_FILE, 'r', encoding='utf-8') as f:
                debt = json.load(f)
        except:
            debt = {}
    target_name = str(Path(target).name)
    if target_name not in debt:
        debt[target_name] = {}
    if classification["has_moderate"]:
        if "moderate" not in debt[target_name]:
            debt[target_name]["moderate"] = []
        for err in classification["levels"]["moderate"]:
            if err not in debt[target_name]["moderate"]:
                debt[target_name]["moderate"].append(err)
    if classification["has_cosmetic"]:
        if "cosmetic" not in debt[target_name]:
            debt[target_name]["cosmetic"] = []
        for err in classification["levels"]["cosmetic"]:
            if err not in debt[target_name]["cosmetic"]:
                debt[target_name]["cosmetic"].append(err)
    with open(DEBT_FILE, 'w', encoding='utf-8') as f:
        json.dump(debt, f, ensure_ascii=False, indent=2)

# ============================================================================
# اجرای جراحی
# ============================================================================

def run_surgery(target, rounds, position):
    cmd = [sys.executable, str(SOURCE), target, "--rounds", str(rounds)]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1, universal_newlines=True)

    pbar = tqdm(total=rounds, desc=Path(target).name, position=position, leave=True, unit="stage")
    current_stage = 0
    output_lines = []

    q = queue.Queue()
    reader = OutputReader(process, q, target)
    reader.start()

    while True:
        try:
            label, line = q.get(timeout=0.1)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        output_lines.append(line)
        if line.startswith("PROGRESS:"):
            try:
                stage_str = line.split(":")[1].strip()
                stage, total = map(int, stage_str.split('/'))
                if stage > current_stage:
                    pbar.update(stage - current_stage)
                    current_stage = stage
            except:
                pass

    process.wait()
    pbar.close()

    final_status = "UNKNOWN"
    for line in reversed(output_lines):
        if "FINAL STATUS: CLEAN" in line:
            final_status = "CLEAN"
            break
        elif "FINAL STATUS: NOT CLEAN" in line:
            final_status = "NOT_CLEAN"
            break

    pdf = Path(target).with_suffix(".pdf")
    pdf_created = pdf.exists()

    return {
        "final_status": final_status,
        "returncode": process.returncode,
        "pdf_created": pdf_created,
        "log_preview": ''.join(output_lines[-30:]) if output_lines else "",
    }

# ============================================================================
# نمایش نقشه‌راه
# ============================================================================

def print_roadmap(diagnostics, surgery_results):
    print("\n" + "=" * 80)
    print("📊 نقشه‌راه نهایی")
    print("=" * 80)
    print(f"{'فایل':<40} {'وضعیت':<15} {'سطح خطا':<12} {'دورها':<8} {'PDF':<6} {'نتیجه'}")
    print("-" * 80)

    for diag in diagnostics:
        target = diag["target"]
        name = Path(target).name
        classification = diag["classification"]
        pdf_created = diag["pdf_created"]

        if classification["overall"] == "healthy":
            status = "✅ سالم"
            level = "—"
            rounds = "۰"
            pdf_status = "✅" if pdf_created else "❌"
            final = "سالم"
            print(f"{name:<40} {status:<15} {level:<12} {rounds:<8} {pdf_status:<6} {final}")
            print(f"   📌 این فایل بدون خطای جدی کامپایل شده است.")
        elif classification["has_critical"]:
            status = "❌ بیمار (جدی)"
            level = "جدی"
            if target in surgery_results:
                result = surgery_results[target]
                final = "پاک" if result["final_status"] == "CLEAN" else "ناتمام"
                pdf_status = "✅" if result["pdf_created"] else "❌"
                rounds = "?"  # مقداردهی موقت
                if result["pdf_created"]:
                    print(f"{name:<40} {status:<15} {level:<12} {rounds:<8} {pdf_status:<6} {final}")
                    print(f"   ✅ خطاهای جدی برطرف شد و PDF تولید گردید.")
                    if DEBT_FILE.exists():
                        try:
                            with open(DEBT_FILE, 'r', encoding='utf-8') as f:
                                debt = json.load(f)
                            if name in debt:
                                if debt[name].get("moderate"):
                                    print(f"   ⚠️ خطاهای سطح متوسط باقی‌مانده: {', '.join(debt[name]['moderate'])}")
                                if debt[name].get("cosmetic"):
                                    print(f"   ℹ️ خطاهای سطح سطحی باقی‌مانده: {', '.join(debt[name]['cosmetic'])}")
                        except:
                            pass
                else:
                    print(f"{name:<40} {status:<15} {level:<12} {rounds:<8} {pdf_status:<6} {final}")
                    print(f"   ❌ با وجود جراحی، PDF تولید نشد.")
            else:
                final = "نامشخص"
                pdf_status = "✅" if pdf_created else "❌"
                rounds = "?"
                print(f"{name:<40} {status:<15} {level:<12} {rounds:<8} {pdf_status:<6} {final}")
                print(f"   ⚠️ این فایل خطای جدی دارد اما جراحی نشده است.")
        elif classification["has_moderate"]:
            status = "⚠️ متوسط"
            level = "متوسط"
            rounds = "۰"
            pdf_status = "✅" if pdf_created else "❌"
            final = "موقتی"
            print(f"{name:<40} {status:<15} {level:<12} {rounds:<8} {pdf_status:<6} {final}")
            if pdf_created:
                print(f"   ✅ PDF تولید شده، اما خطاهای متوسط وجود دارند.")
            else:
                print(f"   ❌ PDF تولید نشد، اما خطاها متوسط هستند.")
        else:
            status = "ℹ️ سطحی"
            level = "سطحی"
            rounds = "۰"
            pdf_status = "✅" if pdf_created else "❌"
            final = "موقتی"
            print(f"{name:<40} {status:<15} {level:<12} {rounds:<8} {pdf_status:<6} {final}")
            if pdf_created:
                print(f"   ✅ PDF تولید شده، فقط هشدارهای سطحی وجود دارند.")
            else:
                print(f"   ❌ PDF تولید نشد، اما خطاها سطحی هستند.")

        print("-" * 80)

    print("=" * 80)

# ============================================================================
# تابع اصلی
# ============================================================================

def main():
    # نمایش قابلیت‌های تشخیصی در ابتدا
    show_diagnostic_capabilities()

    # دریافت سطح از کاربر
    level_choice, no_backup = get_level_from_user()

    # پشتیبان‌گیری
    if not no_backup:
        if BACKUP.exists():
            print(f"📁 پشتیبان قبلاً وجود دارد: {BACKUP}")
        else:
            shutil.copy2(SOURCE, BACKUP)
            print(f"📁 پشتیبان گرفته شد: {BACKUP}")

    # خواندن و اصلاح فایل (فقط اگر پچ نشده باشد)
    with open(SOURCE, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = apply_patches(content)
    
    # فقط در صورتی که تغییر کرده باشد، فایل را بازنویسی کن
    if new_content != content:
        with open(SOURCE, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"🔧 فایل {SOURCE} اصلاح شد (پچ‌های جدید اعمال شدند).")
    else:
        print(f"ℹ️ فایل {SOURCE} بدون تغییر باقی ماند.")

    # === مرحله ۱: تشخیص و سطح‌بندی ===
    print("\n🔍 مرحله‌ی تشخیص و سطح‌بندی خطاها...")
    diagnostics = []

    with tqdm(total=len(TARGETS), desc="اسکن فایل‌ها", unit="file", position=0, leave=True) as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(diagnostic_scan, t): t for t in TARGETS}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                diagnostics.append(result)
                target_name = Path(result["target"]).name
                overall = result["classification"]["overall"]

                if overall == "healthy":
                    pbar.set_postfix_str(f"{target_name}: ✅ سالم")
                elif overall == "critical":
                    criticals = ', '.join(result["classification"]["levels"]["critical"][:2])
                    pbar.set_postfix_str(f"{target_name}: ❌ جدی ({criticals})")
                elif overall == "moderate":
                    moderates = ', '.join(result["classification"]["levels"]["moderate"][:2])
                    pbar.set_postfix_str(f"{target_name}: ⚠️ متوسط ({moderates})")
                else:
                    cosmetics = ', '.join(result["classification"]["levels"]["cosmetic"][:2])
                    pbar.set_postfix_str(f"{target_name}: ℹ️ سطحی ({cosmetics})")

                pbar.update(1)

    print("\n📋 خلاصه تشخیص:")
    for diag in diagnostics:
        target_name = Path(diag["target"]).name
        overall = diag["classification"]["overall"]
        if overall == "healthy":
            print(f"  ✅ {target_name}: سالم")
        elif overall == "critical":
            criticals = ', '.join(diag["classification"]["levels"]["critical"])
            print(f"  ❌ {target_name}: خطای جدی ({criticals})")
        elif overall == "moderate":
            moderates = ', '.join(diag["classification"]["levels"]["moderate"])
            print(f"  ⚠️ {target_name}: خطای متوسط ({moderates})")
        else:
            cosmetics = ', '.join(diag["classification"]["levels"]["cosmetic"])
            print(f"  ℹ️ {target_name}: هشدار سطحی ({cosmetics})")

    # === مرحله ۲: جراحی ===
    print("\n🩺 مرحله‌ی جراحی: رفع خطاهای جدی...")
    surgery_tasks = []
    for diag in diagnostics:
        classification = diag["classification"]
        if classification["overall"] == "healthy":
            continue
        if not classification["has_critical"]:
            save_technical_debt(diag["target"], classification)
            print(f"  📝 {Path(diag['target']).name}: خطاهای سطح ۲ و ۳ ذخیره شدند.")
            continue

        rounds = determine_rounds(classification, level_choice)
        if rounds > 0:
            surgery_tasks.append((diag["target"], rounds))

    if not surgery_tasks:
        print("\n🎉 همه فایل‌ها سالم هستند یا فقط خطاهای سطح ۲ و ۳ دارند.")
        print_roadmap(diagnostics, {})
        return

    print(f"\n🔧 شروع جراحی روی {len(surgery_tasks)} فایل...")
    results = {}
    threads = []
    for i, (target, rounds) in enumerate(surgery_tasks):
        t = threading.Thread(
            target=lambda tgt=target, r=rounds, pos=i:
            results.__setitem__(tgt, run_surgery(tgt, r, pos))
        )
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    # === مرحله ۳: نمایش نقشه‌راه ===
    print_roadmap(diagnostics, results)

    # نمایش خطاهای ذخیره‌شده
    if DEBT_FILE.exists():
        try:
            with open(DEBT_FILE, 'r', encoding='utf-8') as f:
                debt = json.load(f)
            if debt:
                print("\n📋 خطاهای سطح ۲ و ۳ ذخیره‌شده:")
                for target, errors in debt.items():
                    if errors.get("moderate"):
                        print(f"  ⚠️ {target}: {', '.join(errors['moderate'])}")
                    if errors.get("cosmetic"):
                        print(f"  ℹ️ {target}: {', '.join(errors['cosmetic'])}")
        except:
            pass

    print("\n✅ همه تست‌ها به پایان رسید.")

if __name__ == "__main__":
    main()