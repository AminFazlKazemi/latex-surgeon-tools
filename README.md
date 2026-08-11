# 🩺 LaTeX Surgeon Tools

### Intelligent LaTeX Diagnosis, Automated Repair & Transactional Recovery

**LaTeX Surgeon Tools** یک سامانه‌ی هوشمند و مهندسی‌شده برای **تشخیص، تحلیل، طبقه‌بندی، تعمیر و اعتبارسنجی خطاهای LaTeX** است.

این پروژه برای کار با اسناد علمی، مقالات پژوهشی، پایان‌نامه‌ها، گزارش‌های فنی و پروژه‌های چندزبانه طراحی شده و تلاش می‌کند فرآیند دشوار و زمان‌بر رفع خطاهای LaTeX را به یک pipeline کنترل‌شده تبدیل کند:

```text
Source
  │
  ▼
Compile
  │
  ▼
Diagnose
  │
  ▼
Classify
  │
  ▼
Identify Root Cause
  │
  ▼
Propose Repair
  │
  ▼
Apply Safe Patch
  │
  ▼
Compile Again
  │
 ┌┴──────────────┐
 ▼               ▼
SUCCESS         FAILURE
 │               │
 ▼               ▼
Keep            Rollback
 │               │
 ▼               ▼
Learn           Record
```

فلسفه‌ی اصلی پروژه این است:

> **Diagnose first. Repair selectively. Verify everything. Roll back when necessary.**

---

# 📌 معرفی کوتاه

LaTeX Surgeon Tools یک ابزار command-line برای مدیریت خطاهای LaTeX است که به‌جای برخورد یکسان با تمام پیام‌های compiler، آن‌ها را بر اساس اهمیت طبقه‌بندی می‌کند.

سه سطح اصلی تشخیص عبارت‌اند از:

```text
❌ Critical
⚠️ Moderate
ℹ️ Cosmetic
```

و چهار سطح جراحی در اختیار کاربر قرار می‌گیرد:

```text
quick
medium
full
complete
```

این ساختار اجازه می‌دهد کاربر بسته به شرایط پروژه تصمیم بگیرد که:

- فقط خطاهای مانع تولید PDF اصلاح شوند؛
- مشکلات متوسط نیز بررسی شوند؛
- تمام خطاها و هشدارها بررسی شوند؛
- یا یک بررسی عمیق و چندمرحله‌ای انجام شود.

---

# 🎯 هدف پروژه

هدف LaTeX Surgeon Tools صرفاً تولید یک PDF قابل کامپایل نیست.

هدف اصلی ایجاد یک فرآیند قابل کنترل برای:

1. تشخیص خطا
2. تعیین شدت خطا
3. تشخیص علت احتمالی
4. انتخاب repair مناسب
5. اعمال تغییر محدود
6. کامپایل مجدد
7. بررسی نتیجه
8. نگهداری backup
9. ثبت خطاهای حل‌نشده
10. امکان ادامه‌ی جراحی در مراحل بعد

است.

---

# 🧠 فلسفه‌ی LaTeX Surgeon

خطاهای LaTeX معمولاً زنجیره‌ای هستند.

برای مثال:

```text
Missing Package
      │
      ▼
Undefined Command
      │
      ▼
Compilation Failure
      │
      ▼
Secondary Errors
      │
      ▼
Dozens of Misleading Diagnostics
```

اگر همه‌ی پیام‌های compiler به یک اندازه مهم در نظر گرفته شوند، ممکن است کاربر وقت زیادی را صرف خطاهای ثانویه کند.

LaTeX Surgeon تلاش می‌کند ابتدا خطاهای بنیادی‌تر را شناسایی کند.

بنابراین فلسفه‌ی پروژه:

```text
Root Cause
    ↓
Primary Error
    ↓
Targeted Repair
    ↓
Verification
    ↓
Secondary Diagnostics
```

است.

---

# ✨ ویژگی‌های اصلی

## 🔎 1. تشخیص خودکار خطاها

سیستم خطاها و هشدارهای compiler را بررسی کرده و آن‌ها را در سطوح مختلف قرار می‌دهد.

---

## 🩺 2. جراحی هدفمند

در سطح `quick` تمرکز روی خطاهای Critical است.

در سطوح بالاتر، Moderate و Cosmetic نیز وارد فرآیند می‌شوند.

---

## 🇮🇷 3. پشتیبانی از فارسی

پروژه برای اسناد فارسی و چندزبانه طراحی شده است و در تشخیص موارد مرتبط با:

- Unicode
- XeLaTeX
- LuaLaTeX
- `polyglossia`
- `csquotes`
- زبان فارسی
- فونت‌های فارسی

توجه ویژه دارد.

---

## 📚 4. BibLaTeX / Biber

برای پروژه‌های علمی، خطاهای bibliography اهمیت زیادی دارند.

LaTeX Surgeon می‌تواند مشکلات مرتبط با:

- citation
- reference
- bibliography
- BibLaTeX
- Biber
- rerunهای موردنیاز

را در فرآیند تشخیص و جراحی بررسی کند.

---

## 🧱 5. اصلاح ساختار سند

در صورت نبود ساختارهای ضروری، ابزار می‌تواند مواردی مانند:

```latex
\begin{document}
```

و:

```latex
\end{document}
```

را تشخیص دهد و در صورت مناسب بودن شرایط، آن‌ها را اضافه کند.

---

## 📦 6. تشخیص Package

مشکلات مربوط به packageهای موردنیاز می‌توانند در فرآیند جراحی بررسی شوند.

نمونه:

```text
Missing package
Package not found
Undefined control sequence
```

---

## 🔤 7. مشکلات فونت

در اسناد فارسی و چندزبانه، فونت یکی از عوامل مهم failure است.

سیستم می‌تواند مشکلات مربوط به محیط فونت را در فرآیند تشخیص در نظر بگیرد.

---

## 🔄 8. کامپایل مجدد و Verification

Repair صرفاً به دلیل اینکه یک تغییر منطقی به نظر می‌رسد پذیرفته نمی‌شود.

پس از اصلاح:

```text
Patch
 ↓
Compile
 ↓
Check
```

انجام می‌شود.

---

## ↩️ 9. Backup

پیش از اعمال تغییرات، امکان ایجاد backup از فایل اصلی وجود دارد.

---

## 🧪 10. Dry Run

کاربر می‌تواند قبل از اعمال واقعی تغییرات، فرآیند را به‌صورت Dry Run اجرا کند.

```bash
python patch_and_test.py --dry-run
```

---

## 📊 11. Technical Debt

خطاهایی که در مراحل فعلی جراحی نمی‌شوند، می‌توانند در:

```text
.latex_technical_debt.json
```

ثبت شوند تا در مراحل بعدی بررسی شوند.

---

## 🧾 12. Logging

اطلاعات اجرای سیستم در مسیرهای مخصوص log ذخیره می‌شوند تا امکان بررسی رفتار ابزار فراهم شود.

---

# 🏗️ معماری کلی

معماری مفهومی سیستم:

```text
┌─────────────────────────────────────┐
│           LaTeX Project             │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│          Initial Compilation        │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│        Diagnostic Extraction        │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│         Error Classification        │
└──────────────────┬──────────────────┘
                   │
          ┌────────┼─────────┐
          ▼        ▼         ▼
      Critical  Moderate  Cosmetic
          │        │         │
          ▼        ▼         ▼
       Repair    Queue     Record
          │
          ▼
┌─────────────────────────────────────┐
│          Safe Repair Engine         │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│        Recompile / Verification     │
└──────────────────┬──────────────────┘
                   │
             ┌─────┴─────┐
             ▼           ▼
          Success      Failure
             │           │
             ▼           ▼
           Keep       Rollback
```

---

# 🔬 چرخه‌ی کامل جراحی

هر اجرای جراحی را می‌توان به شکل زیر در نظر گرفت:

```text
1. Load
   ↓
2. Compile
   ↓
3. Read Log
   ↓
4. Extract Diagnostics
   ↓
5. Classify
   ↓
6. Select Priority
   ↓
7. Generate Repair
   ↓
8. Apply Patch
   ↓
9. Recompile
   ↓
10. Verify
   ↓
11. Keep / Rollback
   ↓
12. Store Technical Debt
```

---

# 📊 طبقه‌بندی خطاها

## ❌ Critical Errors

**تعداد الگوهای تعریف‌شده: ۱۹**

Critical خطاهایی هستند که معمولاً مانع تولید PDF می‌شوند.

نمونه‌ها:

| خطا | توضیح |
|---|---|
| Missing `\begin{document}` | ساختار اصلی سند ناقص است |
| Missing package | dependency موردنیاز موجود نیست |
| Undefined control sequence | command ناشناخته است |
| Emergency stop | compiler مجبور به توقف شده است |
| Brace imbalance | عدم تعادل `{}` |
| Fatal error | خطای توقف‌کننده |

نمونه:

```text
! Undefined control sequence.
```

یا:

```text
! LaTeX Error:
File `somepackage.sty' not found.
```

---

# ⚠️ Moderate Errors

**تعداد الگوهای تعریف‌شده: ۱۱**

این خطاها ممکن است مانع تولید PDF نشوند اما می‌توانند کیفیت یا کامل بودن خروجی را تحت تأثیر قرار دهند.

نمونه‌ها:

| خطا | توضیح |
|---|---|
| Undefined citation | citation ناشناخته |
| Undefined reference | reference حل‌نشده |
| Biber required | نیاز به اجرای Biber |
| Option clash | تضاد optionهای package |
| Rerun needed | نیاز به compile مجدد |
| Empty bibliography | bibliography خالی |

---

# ℹ️ Cosmetic Errors

**تعداد الگوهای تعریف‌شده: ۷**

این موارد معمولاً مانع تولید PDF نمی‌شوند.

نمونه‌ها:

```text
Overfull \hbox
Underfull \hbox
Hyperref warning
TOC warning
Float warning
```

---

# 🩺 Surgery Levels

## Quick

```bash
python patch_and_test.py --level quick
```

هدف:

```text
Critical Errors
```

حدود:

```text
5 rounds
```

مناسب برای:

> سریعاً سند را به وضعیت قابل کامپایل نزدیک کنید.

---

## Medium

```bash
python patch_and_test.py --level medium
```

هدف:

```text
Critical
+
Moderate
```

حدود:

```text
20 rounds
```

---

## Full

```bash
python patch_and_test.py --level full
```

هدف:

```text
Critical
+
Moderate
+
Cosmetic
```

حدود:

```text
50 rounds
```

---

## Complete

```bash
python patch_and_test.py --level complete
```

هدف:

```text
Deep / Complete Analysis
```

حدود:

```text
250 rounds
```

این حالت برای پروژه‌هایی مناسب است که نیاز به بررسی عمیق دارند.

---

# 📋 مقایسه‌ی Surgery Levels

| Level | Critical | Moderate | Cosmetic | حدود دور |
|---|:---:|:---:|:---:|---:|
| `quick` | ✅ | ❌ | ❌ | ~5 |
| `medium` | ✅ | ✅ | ❌ | ~20 |
| `full` | ✅ | ✅ | ✅ | ~50 |
| `complete` | ✅ | ✅ | ✅ | ~250 |

---

# 🚀 نصب

## Requirements

حداقل:

```text
Python 3.10+
```

همچنین یکی از:

```text
MiKTeX
TeX Live
```

و compilerهای موردنیاز:

```text
XeLaTeX
LuaLaTeX
pdfLaTeX
```

---

# 🪟 نصب در Windows

ابتدا Python را بررسی کنید:

```powershell
python --version
```

سپس LaTeX:

```powershell
xelatex --version
```

و:

```powershell
lualatex --version
```

---

# 📦 نصب وابستگی‌های Python

```bash
python -m pip install tqdm colorama psutil
```

یا:

```bash
pip install tqdm colorama psutil
```

---

# 📚 نصب Biber

برای پروژه‌هایی که از BibLaTeX/Biber استفاده می‌کنند:

```bash
biber --version
```

در صورت استفاده از TeX Live:

```bash
tlmgr install biber
```

---

# 🐙 GitHub CLI

برای قابلیت‌های مرتبط با GitHub در صورت نیاز:

```bash
gh --version
```

نصب در Windows:

```powershell
winget install --id GitHub.cli
```

---

# 📥 دریافت Repository

```bash
git clone https://github.com/AminFazlKazemi/latex-surgeon-tools.git
```

سپس:

```bash
cd latex-surgeon-tools
```

---

# ⚡ Quick Start

پس از نصب:

```bash
python -m pip install tqdm colorama psutil
```

بررسی LaTeX:

```bash
xelatex --version
```

سپس:

```bash
python patch_and_test.py --level quick
```

اگر بررسی عمیق‌تر لازم بود:

```bash
python patch_and_test.py --level full
```

یا:

```bash
python patch_and_test.py --level complete
```

---

# ▶️ اجرای مستقیم

برای یک فایل:

```bash
python latex_surgeon.py article.tex
```

مثال:

```bash
python latex_surgeon.py paper.tex
```

---

# 🧪 اجرای Patch & Test

```bash
python patch_and_test.py
```

این حالت برای اجرای فرآیند تشخیص اولیه، سطح‌بندی و تست طراحی شده است.

---

# 🎚️ CLI

## انتخاب Level

```bash
python patch_and_test.py --level quick
```

```bash
python patch_and_test.py --level medium
```

```bash
python patch_and_test.py --level full
```

```bash
python patch_and_test.py --level complete
```

---

# 👁️ Dry Run

برای اجرای آزمایشی:

```bash
python patch_and_test.py --dry-run
```

Dry Run برای بررسی رفتار ابزار پیش از اعمال تغییرات واقعی مفید است.

---

# 📈 Progress Bar

برای پردازش چند فایل، نمایش پیشرفت می‌تواند مشابه زیر باشد:

```text
اسکن فایل‌ها: 100%|██████████| 3/3 [00:45<00:00]
```

---

# 📁 خروجی‌ها

LaTeX Surgeon Tools می‌تواند فایل‌ها و پوشه‌های مدیریتی ایجاد کند.

## Technical Debt

```text
.latex_technical_debt.json
```

برای ذخیره‌ی مشکلاتی که هنوز در سطح فعلی جراحی رفع نشده‌اند.

---

## Backup

```text
.latex_surgeon_backups/
```

برای نگهداری نسخه‌های پشتیبان.

---

## Logs

```text
.latex_surgeon_logs/
```

برای نگهداری لاگ اجرای ابزار.

---

## Internal Data

```text
.latex_surgeon_internal/
```

برای اطلاعات داخلی موردنیاز debugging و بررسی عملکرد.

---

# 📂 نمونه ساختار پروژه پس از اجرا

```text
project/
│
├── paper.tex
├── references.bib
│
├── .latex_technical_debt.json
│
├── .latex_surgeon_backups/
│   └── ...
│
├── .latex_surgeon_logs/
│   └── ...
│
└── .latex_surgeon_internal/
    └── ...
```

---

# ⚙️ تنظیمات پیشرفته

در `latex_surgeon.py` می‌توان `DEFAULT_CONFIG` را تنظیم کرد.

نمونه:

```python
DEFAULT_CONFIG = {
    "max_rounds": 60,
    "min_repair_confidence": 0.93,
    "timeout": 180,
    "auto_backup": True,
}
```

---

## `max_rounds`

```python
"max_rounds": 60
```

حداکثر تعداد دورهای جراحی.

---

## `min_repair_confidence`

```python
"min_repair_confidence": 0.93
```

حداقل اطمینان موردنیاز برای repair.

---

## `timeout`

```python
"timeout": 180
```

زمان انتظار برای هر compilation برحسب ثانیه.

---

## `auto_backup`

```python
"auto_backup": True
```

فعال‌سازی backup خودکار.

---

# 🗂️ تنظیم مسیرهای پروژه

در صورت استفاده از ساختار توسعه‌ی فعلی، می‌توان مسیرها را تنظیم کرد.

مثال:

```python
SOURCE = Path(
    r"K:\kazemi\papers\poetry\latex_surgeon.py"
)

TARGETS = [
    r"K:\kazemi\papers\poetry\She-rAI\SherAI_Paper_English_Final.tex",
    r"K:\kazemi\papers\poetry\She-rAI\sherai_guide_final.tex",
    r"K:\kazemi\papers\poetry\She-rAI\SherAI_Paper_Persian_Final.tex",
]
```

> این مسیرها مربوط به یک محیط توسعه‌ی نمونه هستند و باید در محیط کاربر با مسیر واقعی جایگزین شوند.

---

# 🇮🇷 Persian / Unicode Workflow

برای پروژه‌های فارسی، پیشنهاد می‌شود compiler مناسب انتخاب شود.

برای مثال:

```text
Persian Document
       ↓
XeLaTeX / LuaLaTeX
       ↓
Unicode
       ↓
Font Handling
       ↓
polyglossia / xepersian
       ↓
Compile
```

---

# 📚 Bibliography Workflow

برای پروژه‌ای با BibLaTeX:

```text
.tex
 │
 ▼
LaTeX
 │
 ▼
.bcf
 │
 ▼
Biber
 │
 ▼
.bbl
 │
 ▼
LaTeX
 │
 ▼
PDF
```

اگر compiler اعلام کند که Biber موردنیاز است، این وضعیت می‌تواند به‌عنوان Moderate diagnostic شناسایی شود.

---

# 🧩 Package Problems

نمونه:

```text
! LaTeX Error:
File `booktabs.sty' not found.
```

این نوع مشکل در دسته‌ی Critical قرار می‌گیرد، زیرا ممکن است compilation را متوقف کند.

---

# 🔧 Undefined Control Sequence

نمونه:

```text
! Undefined control sequence.
l.123 \somecommand
```

سیستم می‌تواند آن را به‌عنوان یک Critical diagnostic شناسایی کند.

یکی از دلایل رایج:

```text
Missing Package
```

است.

---

# 🧱 Document Boundary

نمونه‌ی مشکل:

```latex
\documentclass{article}

\section{Introduction}
```

در صورت نبود:

```latex
\begin{document}
```

ساختار سند ناقص است.

LaTeX Surgeon این نوع مشکل ساختاری را در فرآیند تشخیص بررسی می‌کند.

---

# 📖 Citation Problems

نمونه:

```text
Citation `Smith2025' undefined
```

این نوع خطا معمولاً در دسته‌ی Moderate قرار می‌گیرد.

ممکن است نیاز به:

```text
Biber
```

یا:

```text
additional LaTeX run
```

وجود داشته باشد.

---

# 🔄 Rerun Detection

برخی اسناد برای تکمیل:

- reference
- citation
- TOC
- bibliography

به اجرای مجدد LaTeX نیاز دارند.

این وضعیت می‌تواند به‌عنوان یک diagnostic جداگانه در فرآیند جراحی در نظر گرفته شود.

---

# ⚔️ Option Clash

نمونه:

```text
Option clash for package ...
```

این خطا می‌تواند ناشی از بارگذاری یک package با گزینه‌های ناسازگار باشد.

در سطح Moderate قابل بررسی است.

---

# 📦 Missing Package Recovery

فرآیند مفهومی:

```text
Compiler
   ↓
Missing Package
   ↓
Extract Package Name
   ↓
Check Availability
   ↓
Install / Recover
   ↓
Verify
   ↓
Recompile
```

---

# 🔤 Font Problems

در پروژه‌های چندزبانه ممکن است compiler با خطاهایی مانند:

```text
Font not found
```

متوقف شود.

این مشکلات باید در کنار:

```text
fontspec
polyglossia
XeLaTeX
LuaLaTeX
```

بررسی شوند.

---

# 🧪 نمونه اجرای کامل

فرض کنید:

```text
paper.tex
```

داریم.

ابتدا:

```bash
python latex_surgeon.py paper.tex
```

اگر خطاهای جدی وجود داشت:

```text
Critical diagnostics detected
```

می‌توان از:

```bash
python patch_and_test.py --level quick
```

استفاده کرد.

سپس برای بررسی عمیق‌تر:

```bash
python patch_and_test.py --level full
```

و در نهایت:

```bash
python patch_and_test.py --level complete
```

---

# 🧪 سناریوی پیشنهادی برای مقاله‌ی علمی

برای یک مقاله‌ی مهم:

```text
                 Git Commit
                     │
                     ▼
                  Backup
                     │
                     ▼
                 Dry Run
                     │
                     ▼
               Quick Surgery
                     │
                     ▼
                 Compile
                     │
                     ▼
             Medium Surgery
                     │
                     ▼
                Full Surgery
                     │
                     ▼
           Final Manual Review
```

---

# 🛡️ Best Practices

## قبل از جراحی

```text
✔ Git commit
✔ Backup
✔ بررسی compiler
✔ بررسی نسخه Python
✔ بررسی Biber در صورت نیاز
```

---

## هنگام جراحی

```text
✔ ابتدا quick
✔ سپس medium
✔ سپس full
✔ complete فقط در صورت نیاز
```

---

## پس از جراحی

```text
✔ Compile
✔ PDF inspection
✔ بررسی bibliography
✔ بررسی references
✔ بررسی layout
✔ بررسی فونت‌ها
✔ بررسی تغییرات source
```

---

# ⚠️ محدودیت‌ها

LaTeX Surgeon Tools یک سیستم automated repair است و تضمین نمی‌کند هر خطای ممکن را بدون دخالت انسانی حل کند.

موارد پیچیده ممکن است نیازمند بررسی دستی باشند، از جمله:

- packageهای اختصاصی
- templateهای دانشگاهی
- macroهای بسیار پیچیده
- dependencyهای خارجی
- فایل‌های asset ناقص
- تصاویر خراب
- package conflictهای پیچیده
- خطاهای منطقی در document
- مشکلات سیستم‌عامل
- مشکلات نصب LaTeX

---

# 🧠 Human-in-the-Loop

هدف پروژه حذف کامل انسان از فرآیند نیست.

بهتر است LaTeX Surgeon را به‌عنوان:

```text
Intelligent Assistant
```

در نظر گرفت.

یعنی:

```text
Machine
  ↓
Detect
  ↓
Analyze
  ↓
Repair
  ↓
Verify

Human
  ↓
Review
  ↓
Approve
  ↓
Publish
```

---

# 🧪 Testing

برای توسعه‌ی repairهای جدید، هر repair باید تا حد امکان با یک سناریوی reproducible آزمایش شود.

چرخه‌ی تست:

```text
Broken LaTeX
     ↓
Expected Diagnostic
     ↓
Expected Repair
     ↓
Compile
     ↓
Expected Result
```

---

# 🧩 افزودن Repair Rule جدید

برای افزودن rule جدید، ساختار پیشنهادی:

```text
1. Define Diagnostic
2. Identify Root Cause
3. Create Repair Proposal
4. Set Confidence
5. Validate Source
6. Apply Patch
7. Compile
8. Verify
9. Rollback on Failure
10. Add Regression Test
```

---

# 🤝 Contribution

مشارکت در پروژه آزاد است.

برای گزارش Bug بهتر است اطلاعات زیر ارائه شود:

```text
Operating System:
Python Version:
LaTeX Distribution:
LaTeX Version:
Compiler:
Biber Version:
Surgery Level:
Error Message:
Minimal Reproducible Example:
```

---

# 🐛 گزارش Bug

برای خطاهای قابل بازتولید، یک Issue ایجاد کنید.

یک گزارش خوب شامل:

### Environment

```text
Windows 11
Python 3.x
MiKTeX / TeX Live
XeLaTeX
```

### Command

```bash
python patch_and_test.py --level full
```

### Error

```text
...
```

### Expected

```text
...
```

### Actual

```text
...
```

---

# 🔧 Pull Request

فرآیند پیشنهادی:

```text
Fork
 ↓
Branch
 ↓
Implement
 ↓
Test
 ↓
Commit
 ↓
Push
 ↓
Pull Request
```

---

# 🗺️ Roadmap

## Phase 1 — Core

- [x] Error detection
- [x] Error classification
- [x] Surgery levels
- [x] Direct execution
- [x] Backup
- [x] Logging
- [x] Dry Run
- [x] Technical Debt

---

## Phase 2 — LaTeX Intelligence

- [x] Structural diagnostics
- [x] Package diagnostics
- [x] Undefined command detection
- [x] Persian support
- [x] Unicode awareness
- [x] Bibliography diagnostics
- [x] Biber awareness

---

## Phase 3 — Advanced Recovery

- [ ] Expanded package recovery
- [ ] Expanded font recovery
- [ ] Advanced package conflict resolution
- [ ] More structural repair rules
- [ ] Expanded bibliography recovery
- [ ] More regression tests

---

## Phase 4 — Developer Ecosystem

پیشنهادهای توسعه‌ی آینده:

- [ ] PyPI package
- [ ] Configuration file
- [ ] JSON diagnostics API
- [ ] HTML reports
- [ ] VS Code integration
- [ ] GitHub Action
- [ ] CI/CD
- [ ] Docker environment
- [ ] Plugin architecture
- [ ] Public repair-rule registry

---

# 📦 Repository Release Structure

ساختار پایه:

```text
latex-surgeon-tools/
│
├── README.md
├── latex_surgeon.py
└── patch_and_test.py
```

ساختار توسعه‌یافته‌ی پیشنهادی:

```text
latex-surgeon-tools/
│
├── README.md
├── LICENSE
├── CITATION.cff
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── requirements.txt
│
├── latex_surgeon.py
├── patch_and_test.py
│
├── tests/
│   ├── test_diagnostics.py
│   ├── test_repairs.py
│   └── fixtures/
│
└── docs/
    ├── architecture.md
    └── troubleshooting.md
```

---

# 📤 انتشار در GitHub

اگر از:

```text
push_to_separate_repo.py
```

استفاده می‌کنید، `FILES_TO_PUSH` باید شامل README نیز باشد:

```python
FILES_TO_PUSH = [
    Path(r"K:\kazemi\papers\poetry\latex_surgeon.py"),
    Path(r"K:\kazemi\papers\poetry\patch_and_test.py"),
    Path(r"K:\kazemi\papers\poetry\README.md"),
]
```

سپس:

```bash
python push_to_separate_repo.py
```

---

# 📌 بررسی نهایی Repository

پس از push:

```bash
git status
```

سپس:

```bash
git add README.md latex_surgeon.py patch_and_test.py
```

و:

```bash
git commit -m "docs: add comprehensive README"
```

و:

```bash
git push
```

---

# 🌐 Repository

## GitHub

https://github.com/AminFazlKazemi/latex-surgeon-tools

---

# 📧 Contact

**Email:**

research@sherai.org

**GitHub:**

https://github.com/AminFazlKazemi/latex-surgeon-tools

---

# 📜 License

این پروژه تحت:

**MIT License**

منتشر شده است.

---

# ⚠️ Disclaimer

LaTeX Surgeon Tools یک ابزار کمکی برای تشخیص و تعمیر خودکار خطاهای LaTeX است.

هیچ repair خودکاری نباید بدون بررسی مناسب برای یک manuscript نهایی و حساس پذیرفته شود.

به‌خصوص قبل از:

- ارسال مقاله
- ارسال پایان‌نامه
- انتشار کتاب
- انتشار نسخه نهایی گزارش

خروجی PDF و تغییرات source را بررسی کنید.

---

# ❓ FAQ

## آیا فقط برای فارسی است؟

خیر.

پروژه برای اسناد LaTeX عمومی طراحی شده، اما قابلیت‌هایی برای پروژه‌های فارسی و چندزبانه نیز دارد.

---

## آیا فقط XeLaTeX را پشتیبانی می‌کند؟

خیر.

محیط‌های:

```text
XeLaTeX
LuaLaTeX
pdfLaTeX
```

در نظر گرفته شده‌اند.

---

## آیا Biber اجباری است؟

خیر.

فقط پروژه‌هایی که از bibliography مبتنی بر Biber استفاده می‌کنند به آن نیاز دارند.

---

## آیا اجرای ابزار فایل اصلی را تغییر می‌دهد؟

در حالت جراحی، ممکن است تغییرات روی source اعمال شوند؛ به همین دلیل قابلیت backup در نظر گرفته شده است.

برای بررسی قبل از تغییر:

```bash
python patch_and_test.py --dry-run
```

را اجرا کنید.

---

## آیا همه‌ی خطاها خودکار رفع می‌شوند؟

خیر.

ابزار برای مجموعه‌ای از خطاها و الگوهای شناخته‌شده طراحی شده است و خطاهای پیچیده ممکن است نیازمند مداخله‌ی انسانی باشند.

---

## بهترین Level برای شروع چیست؟

برای شروع معمولاً:

```bash
python patch_and_test.py --level quick
```

مناسب است.

سپس می‌توان در صورت نیاز به:

```bash
--level medium
```

و:

```bash
--level full
```

رفت.

---

## چه زمانی `complete` استفاده کنم؟

برای پروژه‌های بزرگ یا زمانی که می‌خواهید بررسی عمیق‌تری انجام شود:

```bash
python patch_and_test.py --level complete
```

---

# 📋 Command Cheat Sheet

| کار | دستور |
|---|---|
| اجرای مستقیم | `python latex_surgeon.py paper.tex` |
| اجرای ابزار | `python patch_and_test.py` |
| Quick | `python patch_and_test.py --level quick` |
| Medium | `python patch_and_test.py --level medium` |
| Full | `python patch_and_test.py --level full` |
| Complete | `python patch_and_test.py --level complete` |
| Dry Run | `python patch_and_test.py --dry-run` |
| Python version | `python --version` |
| XeLaTeX version | `xelatex --version` |
| LuaLaTeX version | `lualatex --version` |
| pdfLaTeX version | `pdflatex --version` |
| Biber version | `biber --version` |
| GitHub CLI | `gh --version` |

---

# 🧭 Recommended Workflow

برای استفاده‌ی حرفه‌ای:

```text
                    ┌───────────────┐
                    │  LaTeX Project│
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Git Commit │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Dry Run    │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ Quick Surgery │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Compile    │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │Medium Surgery │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │  Full Surgery │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │ Final Review  │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Publish    │
                    └───────────────┘
```

---

# 🏆 Project Philosophy

LaTeX Surgeon Tools تلاش می‌کند یک اصل ساده را دنبال کند:

```text
Do not treat every warning as a fatal error.
Do not treat every error as cosmetic.
Do not repair blindly.
Do not lose the original source.
Do not trust a patch until compilation confirms it.
```

یا به زبان ساده‌تر:

> **اول تشخیص بده؛ بعد جراحی کن؛ سپس دوباره کامپایل کن؛ و در نهایت نتیجه را بررسی کن.**

---

# 🩺 LaTeX Surgeon Tools

### Diagnose.

### Classify.

### Repair.

### Verify.

### Recover.

---

> **LaTeX Surgeon Tools — جراح لاتکس شما.**

⭐ اگر پروژه برای شما مفید است، Repository را Star کنید.

🐛 اگر خطایی پیدا کردید، Issue ایجاد کنید.

💡 اگر repair جدیدی دارید، پیشنهاد دهید.

🔧 اگر می‌خواهید در توسعه مشارکت کنید، Pull Request ارسال کنید.

---

**Repository:**  
https://github.com/AminFazlKazemi/latex-surgeon-tools

**Author:**  
Amin Fazl Kazemi

**Contact:**  
research@sherai.org

**License:**  
MIT